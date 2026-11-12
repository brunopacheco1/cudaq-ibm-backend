# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""What the user sees when IBM misbehaves. Each probe has its own server
with one fault (probe_server.py)."""
import time

from lib import *


@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0]); x.ctrl(q[0], q[1])


def go():
    ibm()
    t = time.monotonic()
    try:
        got = counts(cudaq.sample(bell, shots_count=100))
    except BaseException as error:  # noqa: BLE001
        return {"outcome": "error", "seconds": round(time.monotonic() - t, 1),
                "detail": f"{type(error).__name__}: {str(error).strip()[:500]}"}
    ok = set(got) <= {"00", "11"} and sum(got.values()) == 100
    return {"outcome": "answer" if ok else "ODD-ANSWER", "seconds": round(time.monotonic() - t, 1),
            "detail": f"returned {top(got)} ({sum(got.values())} samples for 100 shots)"}


def e_login_500(): return go()
def e_login_answers_html(): return go()
def e_login_without_a_token(): return go()
def e_login_takes_45_s(): return go()
def e_configuration_500(): return go()
def e_configuration_answers_html(): return go()
def e_backend_not_found_404(): return go()
def e_properties_empty(): return go()
def e_properties_503(): 
    ibm(backend="ibm_no_properties")
    try:
        cudaq.sample(bell); return {"outcome": "UNEXPECTED", "detail": "a job ran without calibration data"}
    except RuntimeError as error:
        return {"outcome": "error", "detail": str(error)[:400]}
def e_job_post_401(): return go()
def e_job_post_429(): return go()
def e_job_post_500(): return go()
def e_job_post_500_once(): return go()
def e_job_post_without_an_id(): return go()
def e_job_post_answers_html(): return go()
def e_job_post_takes_75_s(): return go()
def e_poll_500_once(): return go()
def e_poll_500_always(): return go()


def e_poll_500_once_then_ask_again():
    """The way around a failed wait: sample_async, and ask the same future
    again."""
    ibm()
    future = cudaq.sample_async(bell, shots_count=100)
    saved = str(future)
    try:
        future.get()
        return {"outcome": "note", "detail": "the first get() did not fail"}
    except RuntimeError as error:
        first = str(error)[:80]
    try:
        got = counts(cudaq.AsyncSampleResult(saved).get())
    except RuntimeError as error:
        return {"outcome": "error", "detail": f"first get(): {first}; second get(): {str(error)[:200]}"}
    return {"outcome": "answer", "detail": f"first get() failed ({first}); a future rebuilt from its saved text gave {top(got)}"}

def e_poll_404(): return go()
def e_poll_answers_html(): return go()
def e_status_failed(): return go()
def e_status_cancelled(): return go()
def e_status_unknown_word(): return go()
def e_status_missing(): return go()
def e_status_in_lower_case(): return go()
def e_job_never_finishes(): return go()
def e_results_500(): return go()
def e_results_empty(): return go()
def e_results_half_the_samples(): return go()
def e_results_two_registers(): return go()
def e_results_without_num_bits(): return go()
def e_results_bad_hex(): return go()
def e_results_sample_too_wide(): return go()
def e_results_without_results(): return go()
def e_results_register_named_meas(): return go()


e_login_500.fault = "login_500"
e_login_answers_html.fault = "login_html"
e_login_without_a_token.fault = "login_no_token"
e_login_takes_45_s.fault = "login_slow"
e_configuration_500.fault = "config_500"
e_configuration_answers_html.fault = "config_html"
e_backend_not_found_404.fault = "config_404"
e_properties_empty.fault = "props_empty"
e_properties_503.fault = ""
e_job_post_401.fault = "post_401"
e_job_post_429.fault = "post_429"
e_job_post_500.fault = "post_500"
e_job_post_500_once.fault = "post_500_once"
e_job_post_without_an_id.fault = "post_no_id"
e_job_post_answers_html.fault = "post_html"
e_job_post_takes_75_s.fault = "post_slow"
e_poll_500_once.fault = "poll_500_once"
e_poll_500_always.fault = "poll_500"
e_poll_500_once_then_ask_again.fault = "poll_500_once"
e_poll_404.fault = "poll_404"
e_poll_answers_html.fault = "poll_html"
e_status_failed.fault = "status_failed"
e_status_cancelled.fault = "status_cancelled"
e_status_unknown_word.fault = "status_weird"
e_status_missing.fault = "status_none"
e_status_in_lower_case.fault = "status_lower"
e_job_never_finishes.fault = "never_done"
e_results_500.fault = "results_500"
e_results_empty.fault = "results_empty"
e_results_half_the_samples.fault = "results_fewer_samples"
e_results_two_registers.fault = "results_two_registers"
e_results_without_num_bits.fault = "results_no_num_bits"
e_results_bad_hex.fault = "results_bad_hex"
e_results_sample_too_wide.fault = "results_too_wide"
e_results_without_results.fault = "results_no_results"
e_results_register_named_meas.fault = "results_meas_name"
e_job_never_finishes.timeout = 60
e_status_unknown_word.timeout = 60
e_poll_500_always.timeout = 90
e_poll_404.timeout = 90
e_poll_answers_html.timeout = 90
e_job_post_takes_75_s.timeout = 150
e_login_takes_45_s.timeout = 120
