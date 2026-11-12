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
// M2: OpenQASM 2 -> IBM ISA OpenQASM 3, see Qasm2ToIsa.h;
// M3: routing on the chip's wiring, see Layout.h and decision 0009).
// How this file works: docs/architecture.md. Section numbers (§) refer to it.

#include "ChipData.h"
#include "Layout.h"
#include "Qasm2ToIsa.h"
#include "ResultBits.h"
#include "common/ExecutionContext.h"
#include "common/RestClient.h"
#include "common/ServerHelper.h"
#include "nlohmann/json.hpp"
#include "cudaq/runtime/logger/logger.h"
#include "cudaq/utils/cudaq_utils.h"

#include <curl/curl.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <regex>
#include <set>
#include <thread>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <unistd.h> // close, write (mkstemp is in <cstdlib>)

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

  // M3 routing. The chip numbering CUDA-Q routed on (device label -> IBM
  // qubit), set in getPipelineSubstitutions and used in createJob.
  // CUDA-Q calls getPipelineSubstitutions twice per sample (once to
  // compile, once more before createJob), so the chip data is kept for a
  // short time: both calls then build the same layout, with one fetch.
  // Correctness does not depend on it: createJob searches for a placement
  // on whatever layout it has (Layout.h, step 4).
  ibm::Layout layout;
  ibm::Chip cachedChip;
  std::string chipBackend; // backend the cached chip belongs to
  std::chrono::steady_clock::time_point chipFetched{};
  static constexpr int CHIP_CACHE_SECONDS = 60;
  // Device file we wrote (empty when the user gave mapping_file).
  std::string ownDeviceFile;
  // Pauses before the 2nd and 3rd try of the results GET (quality step 2).
  // Tests override them with CUDAQ_IBM_RETRY_WAITS_MS, a comma-separated
  // list (empty: no retry).
  std::vector<int> retryWaitsMs{2000, 4000};
  // Job status words we did not know and already warned about.
  std::set<std::string> unknownStatuses;

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

  // "https://host/api/" and "https://host/api" are the same base URL.
  static std::string withoutTrailingSlash(std::string url) {
    while (!url.empty() && url.back() == '/')
      url.pop_back();
    return url;
  }

  // Run one of our own requests and read its reply. A reply that is not
  // JSON, or that lacks a field we need, gets a message that names the
  // request instead of the JSON library's bare text (architecture.md §8
  // item 9). Not for the login: its reply may hold the token.
  template <typename F>
  static auto readReply(const std::string &what, F &&f) -> decltype(f()) {
    try {
      return f();
    } catch (const nlohmann::json::parse_error &e) {
      throw std::runtime_error("IBM: the reply to " + what +
                               " is not JSON (" + e.what() + ").");
    } catch (const nlohmann::json::exception &e) {
      throw std::runtime_error("IBM: the reply to " + what +
                               " lacks what IBM documents (" + e.what() +
                               ").");
    }
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

    // The body is never shown from here on: it may hold the token.
    nlohmann::json body;
    try {
      body = nlohmann::json::parse(response);
    } catch (const nlohmann::json::exception &) {
      throw std::runtime_error("IBM IAM: the login reply is not JSON (HTTP " +
                               std::to_string(status) +
                               "). Check iam_url, or try again later.");
    }
    if (!body.is_object() || !body.contains("access_token") ||
        !body.at("access_token").is_string())
      throw std::runtime_error(
          "IBM IAM: the login reply has no 'access_token' (HTTP " +
          std::to_string(status) + "). Check iam_url, or try again later.");
    const auto now = std::chrono::system_clock::now();
    int expiresIn = 3600;
    if (auto it = body.find("expires_in");
        it != body.end() && it->is_number_integer())
      expiresIn = it->get<int>();
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

  // ---- Chip data for routing (M3) -----------------------------------------
  // GET /backends/{name}/configuration (wiring) and /properties (errors).
  // Fail closed (decision 0009, item 3): if /properties cannot be read we
  // stop, because without it a cz could land on a broken link and waste QPU
  // time. A retry is free; mapping_file is the way around. The parsing and
  // the rules for unreadable entries are in ChipData.h.
  ibm::Chip fetchChip() {
    const bool verifyTls = true;
    const std::string base = baseUrl + "/backends/" + backend;
    RestClient client;
    auto headers = getHeaders();
    const ServerMessage config = readReply(
        "GET /backends/" + backend + "/configuration",
        [&] {
          return client.get(base + "/configuration", "", headers, verifyTls);
        });
    ServerMessage props;
    try {
      props = client.get(base + "/properties", "", headers, verifyTls);
    } catch (const std::exception &e) {
      throw std::runtime_error(
          "IBM: cannot read /properties for " + backend + " (" + e.what() +
          "). It is needed to avoid broken qubits and links. Try again, or "
          "give a device file with the mapping_file target argument.");
    }

    ibm::ChipDataReport report;
    ibm::Chip chip = ibm::chipFromIbmJson(config, props, backend, report);
    if (!report.clean())
      CUDAQ_WARN("IBM: /properties for {}: {} unreadable entries, {} links "
                 "without a cz error (not used), {} qubits without a readout "
                 "error (never the root).",
                 backend, report.unreadable, report.unknown.links,
                 report.unknown.qubits);
    if (report.staleQubits > 0)
      CUDAQ_INFO("IBM: {} qubits of {} are not used: IBM reports their sx or "
                 "x error as 1 (stale benchmark).",
                 report.staleQubits, backend);
    return chip;
  }

  // Write the device file. Each write goes to a fresh private temp file
  // (mkstemp, written through its descriptor: no name races in /tmp), which
  // then replaces the previous one in one rename, so CUDA-Q never reads a
  // half-written file. Same path on every compile; removed in the destructor.
  void writeDeviceFile(const std::string &text) {
    std::string tmp =
        (std::filesystem::temp_directory_path() / "cudaq-ibm-device-XXXXXX")
            .string();
    const int fd = mkstemp(tmp.data());
    if (fd < 0)
      throw std::runtime_error("IBM: cannot create the device file " + tmp);
    std::size_t done = 0;
    while (done < text.size()) {
      const ssize_t n = ::write(fd, text.data() + done, text.size() - done);
      if (n <= 0) {
        close(fd);
        std::remove(tmp.c_str());
        throw std::runtime_error("IBM: cannot write the device file " + tmp);
      }
      done += static_cast<std::size_t>(n);
    }
    close(fd);
    if (ownDeviceFile.empty()) {
      ownDeviceFile = tmp;
      return;
    }
    if (std::rename(tmp.c_str(), ownDeviceFile.c_str()) != 0) {
      std::remove(tmp.c_str());
      throw std::runtime_error("IBM: cannot replace the device file " +
                               ownDeviceFile);
    }
  }

public:
  ~IBMServerHelper() override {
    if (!ownDeviceFile.empty()) {
      std::error_code ec;
      std::filesystem::remove(ownDeviceFile, ec);
    }
  }

  const std::string name() const override { return "ibm"; }

  // M3. Called by CUDA-Q at every compile (decision 0009, D3): fetch the
  // chip (kept 60 s, see `chip` above), number it best-first from the
  // root with the best 10-qubit patch (decision 0012), and hand CUDA-Q the
  // device file for `qubit-mapping{device=file(%QPU_ARCH%)}`.
  std::map<std::string, std::string>
  getPipelineSubstitutions(const std::filesystem::path &) override {
    // This is the first of our code CUDA-Q calls when a kernel is launched,
    // before it compiles the kernel. cudaq.observe is refused here: CUDA-Q
    // would otherwise fail later in its own compiler with an error about
    // "qalloc", or crash Python (docs/decisions/0019).
    if (const auto *context = cudaq::getExecutionContext();
        context != nullptr && context->name == "observe")
      throw std::runtime_error(
          "IBM: cudaq.observe is not supported on the 'ibm' target yet. "
          "Use cudaq.sample: rotate the qubits into the measurement basis "
          "of each term of the observable, and compute the expectation "
          "value from the counts.");
    std::string path;
    if (auto it = backendConfig.find("mapping_file");
        it != backendConfig.end() && !it->second.empty()) {
      // Override for tests: a device file whose node ids ARE IBM ids.
      path = it->second;
      std::ifstream in(path);
      if (!in)
        throw std::runtime_error("IBM: cannot read mapping_file " + path);
      std::stringstream text;
      text << in.rdbuf();
      layout.adj = ibm::parseDeviceFile(text.str());
      if (layout.adj.empty())
        throw std::runtime_error(
            "IBM: mapping_file " + path +
            " has no qubits. A device file has one line per qubit, e.g. "
            "\"0 --> {1, 2}\" (qubit 0 is linked to qubits 1 and 2).");
      layout.ibmId.resize(layout.adj.size());
      for (std::size_t i = 0; i < layout.ibmId.size(); ++i)
        layout.ibmId[i] = static_cast<int>(i);
    } else {
      const auto now = std::chrono::steady_clock::now();
      if (cachedChip.qubits.empty() || chipBackend != backend ||
          now - chipFetched > std::chrono::seconds(CHIP_CACHE_SECONDS)) {
        cachedChip = fetchChip();
        chipBackend = backend;
        chipFetched = now;
      }
      const ibm::Region region = ibm::usableRegion(cachedChip);
      const int root = ibm::chooseRoot(region, cachedChip);
      layout = ibm::bestFirstLayout(region, cachedChip, root);
      writeDeviceFile(ibm::deviceFileText(layout.adj));
      path = ownDeviceFile;
      const ibm::Patch patch =
          ibm::growPatch(region, cachedChip, root, ibm::ROOT_REGION_SIZE);
      CUDAQ_INFO("IBM: {} of {} qubits usable on {}; numbering starts at "
                 "qubit {}; forecast for the first {} qubits: {:.1f}%",
                 region.qubits.size(), cachedChip.qubits.size(), backend, root,
                 patch.ibmId.size(), 100.0 * patch.forecast);
    }
    CUDAQ_INFO("IBM: device file for routing: {}", path);
    // Quoted like IQM does, to protect the path inside the pass option.
    return {{"%QPU_ARCH%", "'" + path + "'"}};
  }

  // §4 initialize. Called on set_target and again inside future::get().
  void initialize(BackendConfig config) override {
    CUDAQ_INFO("Initializing IBM backend.");
    // emulate=True is refused (docs/decisions/0018). In emulation CUDA-Q
    // simulates its own compiled kernel and never calls the gate rewrite,
    // the qubit assignment or the result decoding of this plugin, and with
    // this target's router the bit order of the result can be wrong (F5).
    if (auto it = config.find("emulate");
        it != config.end() && it->second == "true")
      throw std::runtime_error(
          "IBM: the 'ibm' target does not support emulate=True. To simulate "
          "a kernel, use a simulator target, for example "
          "cudaq.set_target(\"qpp-cpu\").");
    backendConfig = config; // keep everything CUDA-Q passes along

    backend = valueOr(config, "backend", DEFAULT_BACKEND);
    baseUrl = withoutTrailingSlash(valueOr(config, "url", DEFAULT_URL)) + "/v1";
    iamUrl = withoutTrailingSlash(valueOr(config, "iam_url", DEFAULT_IAM_URL));
    apiKey = requiredEnv("IBM_QUANTUM_API_KEY");
    crn = requiredEnv("IBM_QUANTUM_CRN");

    if (const char *waits = std::getenv("CUDAQ_IBM_RETRY_WAITS_MS")) {
      retryWaitsMs.clear();
      std::stringstream list(waits);
      std::string item;
      while (std::getline(list, item, ','))
        if (!item.empty())
          retryWaitsMs.push_back(std::stoi(item));
    }

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
      // M3: CUDA-Q routed the circuit, but then packed the qubits it used
      // into labels 0..m-1 (architecture.md §9.2). Find a device qubit for
      // every label such that each 2-qubit gate sits on a link (Layout.h,
      // step 4).
      if (layout.adj.empty())
        throw std::runtime_error(
            "IBM: no chip layout; the kernel was not compiled for 'ibm'.");
      CUDAQ_INFO("IBM: OpenQASM 2 from CUDA-Q for {}:\n{}", circuitCode.name,
                 circuitCode.code);
      const auto interactions = ibm::qasm2Interactions(circuitCode.code);
      const auto place = ibm::assignQubits(interactions.numQubits,
                                           interactions.pairs, layout.adj);
      std::vector<int> physical(place.size());
      std::string mapText;
      for (std::size_t i = 0; i < place.size(); ++i) {
        physical[i] = layout.ibmId[place[i]];
        mapText += (i ? " " : "") + std::to_string(i) + "->" +
                   std::to_string(physical[i]);
      }
      CUDAQ_INFO("IBM: qubit labels -> IBM qubits for {}: {}", circuitCode.name,
                 mapText);

      // M2: CUDA-Q gives us OpenQASM 2 in textbook gates; IBM only accepts
      // OpenQASM 3 in its native gates (an "ISA circuit").
      const auto isa = ibm::qasm2ToIsaQasm3(circuitCode.code, physical);
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
  // A status word we do not know is logged once and polled on: an error
  // would end sample() while the job runs on and is billed (quality step 1).
  bool jobIsDone(ServerMessage &getJobResponse) override {
    const std::string status = readReply("GET /jobs/{id}", [&] {
      return toUpper(
          getJobResponse.at("state").at("status").get<std::string>());
    });
    if (status == "COMPLETED")
      return true;
    if (status == "FAILED" || status == "CANCELLED") {
      std::string reason = getJobResponse["state"].value("reason", "");
      throw std::runtime_error("IBM job ended with status " + status +
                               (reason.empty() ? "" : ": " + reason));
    }
    if (status != "QUEUED" && status != "RUNNING" &&
        unknownStatuses.insert(status).second)
      CUDAQ_WARN("IBM: the job has status '{}', which this plugin does not "
                 "know. It keeps polling every 5 s; stop with Ctrl-C.",
                 status);
    return false; // QUEUED, RUNNING, or a word we do not know
  }

  std::chrono::microseconds
  nextResultPollingInterval(ServerMessage &) override {
    return std::chrono::seconds(5);
  }

  // §3.5, quality step 2. The job has finished and is paid for, so a
  // transient failure of this GET must not lose its samples: try again, as
  // CUDA-Q's qBraid helper does for its results (3 tries, 2 s then 4 s).
  // RestClient reports the HTTP status only inside its error text
  // ("HTTP GET Error - status code 503: ..."), so it is read from there.
  // 401, 403 and 404 cannot get better by waiting: they fail at once.
  ServerMessage fetchResults(const std::string &jobId) {
    static const std::regex statusRe(R"(status code (\d+))");
    const bool verifyTls = true; // RestClient's default is false (§2.2)
    const int tries = static_cast<int>(retryWaitsMs.size()) + 1;
    for (int i = 0;; ++i) {
      try {
        auto headers = getHeaders();
        RestClient client;
        return client.get(baseUrl + "/jobs/" + jobId + "/results", "",
                          headers, verifyTls);
      } catch (const nlohmann::json::exception &) {
        throw; // a reply, but not JSON: readReply explains it
      } catch (const std::exception &e) {
        const std::string text = e.what();
        std::smatch m;
        const int status =
            std::regex_search(text, m, statusRe) ? std::stoi(m[1]) : 0;
        const bool hopeless = status == 401 || status == 403 || status == 404;
        if (hopeless || i + 1 == tries)
          throw std::runtime_error(
              "IBM: GET /jobs/" + jobId + "/results failed" +
              (hopeless ? "" : " after " + std::to_string(tries) + " tries") +
              ": " + text +
              ". The job itself finished on IBM; its results stay there.");
        CUDAQ_WARN("IBM: GET /jobs/{}/results failed ({}); try {} of {} in "
                   "{} ms.",
                   jobId, status ? "HTTP " + std::to_string(status) : text,
                   i + 2, tries, retryWaitsMs[i]);
        std::this_thread::sleep_for(
            std::chrono::milliseconds(retryWaitsMs[i]));
      }
    }
  }

  // §3.5. One extra GET for the samples (same pattern as IonQ).
  sample_result processResults(ServerMessage &getJobResponse,
                               std::string &jobId) override {
    const std::string what = "GET /jobs/" + jobId + "/results";
    ServerMessage results =
        readReply(what, [&] { return fetchResults(jobId); });
    CUDAQ_INFO("IBM: results for job {}: {}", jobId, results.dump());

    std::vector<std::string> hexSamples;
    std::size_t numBits = 0;
    readReply(what, [&] {
      const auto &data = results.at("results").at(0).at("data");
      if (data.size() != 1)
        throw std::runtime_error(
            "IBM: only circuits with one classical register are supported; "
            "got " +
            std::to_string(data.size()));
      const auto &reg = data.begin().value();
      // Our circuit measures every qubit in allocation order (combine-
      // measurements in ibm.yml.in), so c[i] is qubit i. Keep the qubits
      // the user measured, as CUDA-Q's output_names lists them
      // (ResultBits.h).
      for (const auto &s : reg.at("samples"))
        hexSamples.push_back(s.get<std::string>());
      numBits = reg.value("num_bits", 0);
    });
    // Seen only with a faulty server: fewer samples than shots. They are
    // still real samples of a job that is paid for, so warn and return
    // them (quality step 1).
    if (hexSamples.size() != shots)
      CUDAQ_WARN("IBM: job {} returned {} samples for {} shots; the result "
                 "holds the {} samples IBM returned.",
                 jobId, hexSamples.size(), shots, hexSamples.size());
    if (numBits == 0)
      numBits = ibm::widestSample(hexSamples);
    std::vector<std::size_t> measured;
    if (auto it = outputNames.find(jobId); it != outputNames.end())
      for (const auto &[result, info] : it->second)
        measured.push_back(info.qubitNum);
    const auto keep = ibm::keptBits(measured, numBits);

    CountsDictionary counts;
    for (const auto &hex : hexSamples)
      ++counts[ibm::pickBits(ibm::hexToBits(hex, numBits), keep)];
    return sample_result(ExecutionResult(counts));
  }
};

} // namespace cudaq

CUDAQ_REGISTER_TYPE(cudaq::ServerHelper, cudaq::IBMServerHelper, ibm)
