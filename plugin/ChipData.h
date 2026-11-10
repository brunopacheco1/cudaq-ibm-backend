/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Milestone M3: read IBM's backend data into a Chip (see Layout.h).
//
//   GET /backends/{name}/configuration  -> n_qubits, coupling_map (wiring)
//   GET /backends/{name}/properties     -> qubits[], gates[] (error rates,
//                                          "operational" flags)
//
// Policy: fail closed (decision 0009, item 3). The properties tell us which
// qubits and links are broken. A cz on a broken link wastes QPU time, so:
//   - a reply without the "qubits" or "gates" list is an error;
//   - an "operational" or "gate_error" value we cannot read makes that qubit
//     or link broken;
//   - a link with no cz error at all is not used, and a qubit with no readout
//     error is never the root (Layout.h, closeUnknowns);
//   - a qubit whose sx or x error is 1 (or unreadable) is not used. IBM
//     reports 1 when the benchmark of a gate failed for several days: the
//     value is "undefined, proceed with caution" (IBM guide "QPU
//     information"). Seen on ibm_fez on 2026-11-10 for qubits 72, 148, 149.
//     A link whose cz error is 1 is dropped the same way (Layout.h,
//     usableRegion). No sx or x entry at all changes nothing: the plugin
//     does not use these error rates for anything else.
//
// Pure functions: JSON in, Chip out, no network. Unit tested in
// tests/test_chip_data.cpp. Needs only nlohmann/json.

#pragma once

#include "Layout.h"
#include "nlohmann/json.hpp"

#include <cstddef>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

namespace cudaq::ibm {

/// What chipFromIbmJson could not use; the caller logs it.
struct ChipDataReport {
  std::size_t unreadable = 0;  // entries of /properties we could not read
  UnknownCount unknown;        // qubits and links left without an error rate
  std::size_t staleQubits = 0; // qubits not used: sx or x error given as 1
  bool clean() const {
    return unreadable == 0 && unknown.qubits == 0 && unknown.links == 0;
  }
};

/// One "value" of /properties may be a number or a boolean. Throws on
/// anything else (null, text).
inline double ibmNumber(const nlohmann::json &v) {
  if (v.is_boolean())
    return v.get<bool>() ? 1.0 : 0.0;
  return v.get<double>();
}

/// Build the Chip from the two replies. Throws std::runtime_error (with
/// `backend` in the text) when the wiring or the two property lists are
/// missing, or when no link has a cz error rate.
inline Chip chipFromIbmJson(const nlohmann::json &config,
                            const nlohmann::json &props,
                            const std::string &backend,
                            ChipDataReport &report) {
  if (!config.contains("n_qubits") || !config["n_qubits"].is_number() ||
      !config.contains("coupling_map") || !config["coupling_map"].is_array())
    throw std::runtime_error("IBM: /configuration for " + backend +
                             " has no 'n_qubits' or 'coupling_map'.");
  if (!props.contains("qubits") || !props["qubits"].is_array() ||
      !props.contains("gates") || !props["gates"].is_array())
    throw std::runtime_error(
        "IBM: /properties for " + backend +
        " has no 'qubits' or 'gates' list; the format may have changed. "
        "Please report it. Way around: the mapping_file target argument.");

  // Error rates start as "unknown" and are filled from the properties.
  Chip chip;
  chip.qubits.assign(config["n_qubits"].get<int>(),
                     ChipQubit{UNKNOWN_ERROR, true});
  std::map<std::pair<int, int>, std::size_t> linkIndex;
  for (const auto &pair : config["coupling_map"]) {
    const int a = pair.at(0).get<int>(), b = pair.at(1).get<int>();
    linkIndex[{a, b}] = chip.links.size();
    chip.links.push_back({a, b, UNKNOWN_ERROR, true});
  }

  const auto &qubits = props["qubits"];
  for (std::size_t q = 0; q < qubits.size() && q < chip.qubits.size(); ++q) {
    if (!qubits[q].is_array()) {
      ++report.unreadable; // nothing known about q: closeUnknowns handles it
      continue;
    }
    for (const auto &item : qubits[q]) {
      std::string name;
      try {
        name = item.at("name").get<std::string>();
        if (name == "readout_error")
          chip.qubits[q].readoutError = ibmNumber(item.at("value"));
        else if (name == "operational")
          chip.qubits[q].operational = ibmNumber(item.at("value")) != 0.0;
      } catch (const std::exception &) {
        ++report.unreadable;
        if (name == "operational")
          chip.qubits[q].operational = false;
      }
    }
  }

  // 1-qubit gates of the ISA set. rz is a frame change and has no error.
  std::set<int> stale;
  for (const auto &gate : props["gates"]) {
    int q = -1;
    try {
      const auto name = gate.at("gate").get<std::string>();
      if (name != "sx" && name != "x")
        continue;
      const auto &ends = gate.at("qubits");
      if (!ends.is_array() || ends.size() != 1)
        throw std::runtime_error("1-qubit gate entry without one qubit");
      q = ends[0].get<int>();
      if (q < 0 || q >= static_cast<int>(chip.qubits.size())) {
        q = -1;
        continue;
      }
      if (gate.contains("parameters"))
        for (const auto &param : gate["parameters"])
          if (param.at("name").get<std::string>() == "gate_error" &&
              ibmNumber(param.at("value")) >= 1.0)
            stale.insert(q);
    } catch (const std::exception &) {
      ++report.unreadable;
      if (q >= 0)
        chip.qubits[q].operational = false;
    }
  }
  for (int q : stale)
    chip.qubits[q].operational = false;
  report.staleQubits = stale.size();

  for (const auto &gate : props["gates"]) {
    ChipLink *link = nullptr;
    try {
      if (gate.at("gate").get<std::string>() != "cz")
        continue;
      const auto &ends = gate.at("qubits");
      if (!ends.is_array() || ends.size() != 2)
        throw std::runtime_error("cz entry without two qubits");
      auto it = linkIndex.find({ends[0].get<int>(), ends[1].get<int>()});
      if (it == linkIndex.end())
        continue;
      link = &chip.links[it->second];
      if (gate.contains("parameters"))
        for (const auto &param : gate["parameters"]) {
          const auto name = param.at("name").get<std::string>();
          if (name == "gate_error")
            link->czError = ibmNumber(param.at("value"));
          else if (name == "operational")
            link->operational = ibmNumber(param.at("value")) != 0.0;
        }
    } catch (const std::exception &) {
      // Either we do not know which link this is (it then keeps its unknown
      // error), or one of its parameters is unreadable: do not use it.
      ++report.unreadable;
      if (link)
        link->operational = false;
    }
  }

  report.unknown = closeUnknowns(chip);
  if (report.unknown.allLinks > 0 &&
      report.unknown.links == report.unknown.allLinks)
    throw std::runtime_error(
        "IBM: /properties for " + backend +
        " has no cz error rate for any link. The 'ibm' target supports "
        "backends whose 2-qubit gate is cz.");
  return chip;
}

} // namespace cudaq::ibm
