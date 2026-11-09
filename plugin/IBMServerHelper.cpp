/*******************************************************************************
 * Copyright (c) 2022 - 2026 NVIDIA Corporation & Affiliates.                  *
 * All rights reserved.                                                        *
 *                                                                             *
 * Modifications copyright (c) 2026 Bruno Pacheco.                             *
 * Adapted from the CUDA-Q mock_rest plugin example and IonQServerHelper       *
 * for IBM Quantum.                                                            *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// IBM Quantum backend for CUDA-Q (M1: auth, submit, poll, results;
// M2: OpenQASM 2 -> IBM ISA OpenQASM 3, see Qasm2ToIsa.h).
// How this file works: docs/architecture.md. Section numbers (§) refer to it.
//
// Not yet: qubit routing (M3). Circuits must use qubits that are wired
// together on the chip (for M2: qubits 0 and 1).

#include "Qasm2ToIsa.h"
#include "common/RestClient.h"
#include "common/ServerHelper.h"
#include "nlohmann/json.hpp"
#include "cudaq/runtime/logger/logger.h"
#include "cudaq/utils/cudaq_utils.h"

#include <curl/curl.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace cudaq {

class IBMServerHelper : public ServerHelper {
  // ---- Defaults (§3) -------------------------------------------------------
  static constexpr const char *DEFAULT_URL =
      "https://quantum.cloud.ibm.com/api";
  static constexpr const char *DEFAULT_IAM_URL =
      "https://iam.cloud.ibm.com/identity/token";
  static constexpr const char *DEFAULT_BACKEND = "ibm_fez";
  static constexpr int REFRESH_MARGIN_SECONDS = 60;

  // ---- State ---------------------------------------------------------------
  // Secrets live in private members, never in backendConfig, because
  // backendConfig is copied around by CUDA-Q and may end up in logs.
  std::string apiKey;
  std::string crn;
  std::string baseUrl; // e.g. https://quantum.cloud.ibm.com/api/v1
  std::string iamUrl;
  std::string backend;

  // Cached IAM token and when it expires.
  std::string token;
  std::chrono::system_clock::time_point tokenExpires{};

  // CA bundle used to verify IBM's TLS certificates (§2.3).
  std::string caBundle;

  // ---- Small helpers -------------------------------------------------------
  static std::string valueOr(const BackendConfig &config,
                             const std::string &key,
                             const std::string &fallback) {
    auto it = config.find(key);
    return (it != config.end() && !it->second.empty()) ? it->second : fallback;
  }

  static std::string requiredEnv(const char *name) {
    const char *value = std::getenv(name);
    if (value == nullptr || *value == '\0')
      throw std::runtime_error(
          std::string(name) +
          " is not set. Export it before using the 'ibm' target.");
    return value;
  }

  static std::string toUpper(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return std::toupper(c); });
    return s;
  }

  // libcurl calls this for each chunk of the response body.
  static size_t appendToString(char *data, size_t size, size_t count,
                               void *userData) {
    static_cast<std::string *>(userData)->append(data, size * count);
    return size * count;
  }

  // ---- CA bundle (§2.3) ---------------------------------------------------
  // CUDA-Q builds libcurl with no default CA store, so our own libcurl call
  // must name a bundle. Same lookup as RestClient's constructor (0.16.0), so
  // the IAM login and RestClient always trust the same certificates. Never
  // falls back to turning verification off.
  static std::string findCaBundle() {
    namespace fs = std::filesystem;
    std::error_code ec;
    if (const char *env = std::getenv("CURL_CA_BUNDLE");
        env && *env && fs::exists(env, ec))
      return env;
    const fs::path cudaqLib{cudaq::getCUDAQLibraryPath()};
    const fs::path bundled =
        cudaqLib.parent_path().parent_path() / "cacert.pem";
    if (fs::exists(bundled, ec))
      return bundled.string();
    throw std::runtime_error(
        "IBM: no CA bundle found to verify TLS. Set CURL_CA_BUNDLE to a PEM "
        "file, for example /etc/ssl/certs/ca-certificates.crt or one from "
        "https://curl.se/ca/cacert.pem.");
  }

  // ---- IAM login (§3.1) ----------------------------------------------------
  // RestClient::post can only send JSON and logs the body (which would
  // contain the API key), so this one request uses libcurl directly (§2.2).
  std::string requestNewToken() {
    CURL *curl = curl_easy_init();
    if (!curl)
      throw std::runtime_error("IBM IAM: could not initialise libcurl.");

    char *escapedKey =
        curl_easy_escape(curl, apiKey.c_str(), static_cast<int>(apiKey.size()));
    std::string form =
        "grant_type=urn%3Aibm%3Aparams%3Aoauth%3Agrant-type%3Aapikey&apikey=";
    form += escapedKey ? escapedKey : "";
    curl_free(escapedKey);

    curl_slist *headers = nullptr;
    headers = curl_slist_append(headers, "Accept: application/json");
    headers = curl_slist_append(
        headers, "Content-Type: application/x-www-form-urlencoded");

    std::string response;
    curl_easy_setopt(curl, CURLOPT_URL, iamUrl.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, form.c_str());
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, appendToString);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    // libcurl verifies TLS by default, but has no CA store of its own (§2.3).
    curl_easy_setopt(curl, CURLOPT_CAINFO, caBundle.c_str());

    const CURLcode rc = curl_easy_perform(curl);
    long status = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK)
      throw std::runtime_error(std::string("IBM IAM: request failed: ") +
                               curl_easy_strerror(rc));
    if (status < 200 || status >= 300)
      // IAM error bodies do not echo the API key, so they are safe to show.
      throw std::runtime_error("IBM IAM: HTTP " + std::to_string(status) +
                               ": " + response);

    const auto body = nlohmann::json::parse(response);
    const auto now = std::chrono::system_clock::now();
    const int expiresIn = body.value("expires_in", 3600);
    tokenExpires = now + std::chrono::seconds(expiresIn);
    return body.at("access_token").get<std::string>();
  }

  // Return a cached token, refreshing it shortly before it expires.
  const std::string &accessToken() {
    const auto now = std::chrono::system_clock::now();
    if (token.empty() ||
        now >= tokenExpires - std::chrono::seconds(REFRESH_MARGIN_SECONDS)) {
      CUDAQ_INFO("IBM: requesting a new IAM access token.");
      token = requestNewToken();
    }
    return token;
  }

  // ---- Result decoding (§3.5) ----------------------------------------------
  // "0x1" with 2 bits -> "01" (IBM, bit 0 right-most) -> "10" (CUDA-Q,
  // qubit 0 left-most).
  static std::string hexToCudaqBits(const std::string &hex,
                                    std::size_t numBits) {
    unsigned long long value = std::stoull(hex, nullptr, 16);
    std::string bits(numBits, '0');
    for (std::size_t i = 0; i < numBits; ++i)
      bits[i] = ((value >> i) & 1ULL) ? '1' : '0'; // bit i -> position i
    return bits;
  }

public:
  const std::string name() const override { return "ibm"; }

  // §4 initialize. Called on set_target and again inside future::get().
  void initialize(BackendConfig config) override {
    CUDAQ_INFO("Initializing IBM backend.");
    backendConfig = config; // keep everything CUDA-Q passes along

    backend = valueOr(config, "backend", DEFAULT_BACKEND);
    baseUrl = valueOr(config, "url", DEFAULT_URL) + "/v1";
    iamUrl = valueOr(config, "iam_url", DEFAULT_IAM_URL);
    apiKey = requiredEnv("IBM_QUANTUM_API_KEY");
    crn = requiredEnv("IBM_QUANTUM_CRN");

    caBundle = findCaBundle();
    CUDAQ_INFO("IBM: verifying TLS with CA bundle {}", caBundle);

    if (auto it = config.find("shots");
        it != config.end() && !it->second.empty())
      setShots(std::stoul(it->second));

    // Reads output_names.<jobId> etc., used in processResults.
    parseConfigForCommonParams(config);
  }

  // §3.2. Called once per poll loop (see the token-expiry limit).
  RestHeaders getHeaders() override {
    return {{"Authorization", "Bearer " + accessToken()},
            {"Service-CRN", crn},
            {"Accept", "application/json"},
            {"Content-Type", "application/json"}};
  }

  // §3.3. One Sampler job per kernel, one PUB per job.
  ServerJobPayload
  createJob(std::vector<KernelExecution> &circuitCodes) override {
    std::vector<ServerMessage> jobs;
    jobs.reserve(circuitCodes.size());
    for (const auto &circuitCode : circuitCodes) {
      // M2: CUDA-Q gives us OpenQASM 2 in textbook gates; IBM only accepts
      // OpenQASM 3 in its native gates (an "ISA circuit").
      const auto isa = ibm::qasm2ToIsaQasm3(circuitCode.code);
      CUDAQ_INFO("IBM: ISA circuit for {}:\n{}", circuitCode.name, isa.qasm3);
      ServerMessage job;
      job["program_id"] = "sampler";
      job["backend"] = backend;
      job["params"]["pubs"] = nlohmann::json::array(
          {nlohmann::json::array({isa.qasm3, nullptr, shots})});
      job["params"]["version"] = 2;
      jobs.push_back(std::move(job));
    }
    return std::make_tuple(baseUrl + "/jobs", getHeaders(), std::move(jobs));
  }

  std::string extractJobId(ServerMessage &postResponse) override {
    if (!postResponse.contains("id"))
      throw std::runtime_error("IBM: job submission response has no 'id': " +
                               postResponse.dump());
    return postResponse.at("id").get<std::string>();
  }

  std::string constructGetJobPath(std::string &jobId) override {
    return baseUrl + "/jobs/" + jobId;
  }

  std::string constructGetJobPath(ServerMessage &postResponse) override {
    auto jobId = extractJobId(postResponse);
    return constructGetJobPath(jobId);
  }

  // §3.4. Throw on failure, otherwise CUDA-Q would poll forever.
  bool jobIsDone(ServerMessage &getJobResponse) override {
    const std::string status =
        toUpper(getJobResponse.at("state").at("status").get<std::string>());
    if (status == "COMPLETED")
      return true;
    if (status == "FAILED" || status == "CANCELLED") {
      std::string reason = getJobResponse["state"].value("reason", "");
      throw std::runtime_error("IBM job ended with status " + status +
                               (reason.empty() ? "" : ": " + reason));
    }
    return false; // QUEUED, RUNNING, ...
  }

  std::chrono::microseconds
  nextResultPollingInterval(ServerMessage &) override {
    return std::chrono::seconds(5);
  }

  // §3.5. One extra GET for the samples (same pattern as IonQ).
  sample_result processResults(ServerMessage &getJobResponse,
                               std::string &jobId) override {
    auto headers = getHeaders();
    const bool verifyTls = true; // RestClient's default is false (§2.2)
    RestClient client;
    ServerMessage results = client.get(baseUrl + "/jobs/" + jobId + "/results",
                                       "", headers, verifyTls);
    CUDAQ_INFO("IBM: results for job {}: {}", jobId, results.dump());

    const auto &data = results.at("results").at(0).at("data");
    if (data.size() != 1)
      throw std::runtime_error(
          "IBM: only circuits with one classical register are supported "
          "in M1; got " +
          std::to_string(data.size()));
    const auto &reg = data.begin().value();
    const auto &samples = reg.at("samples");

    // Number of bits: prefer what CUDA-Q told us it measured; fall back on
    // IBM's num_bits (§3.5), then on the widest sample.
    std::size_t numBits = 0;
    if (auto it = outputNames.find(jobId); it != outputNames.end())
      numBits = it->second.size();
    if (numBits == 0)
      numBits = reg.value("num_bits", 0);
    if (numBits == 0)
      for (const auto &s : samples) {
        auto v = std::stoull(s.get<std::string>(), nullptr, 16);
        std::size_t width = 0;
        while (width < 64 && (v >> width) != 0)
          ++width;
        numBits = std::max(numBits, width);
      }
    if (numBits == 0)
      numBits = 1;
    if (numBits > 64)
      throw std::runtime_error("IBM: more than 64 measured bits not supported");

    CountsDictionary counts;
    for (const auto &s : samples)
      ++counts[hexToCudaqBits(s.get<std::string>(), numBits)];
    return sample_result(ExecutionResult(counts));
  }
};

} // namespace cudaq

CUDAQ_REGISTER_TYPE(cudaq::ServerHelper, cudaq::IBMServerHelper, ibm)
