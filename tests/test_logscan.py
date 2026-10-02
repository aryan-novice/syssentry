import os

from syssentry.logscan import LogWatch

FAIL = "Oct  2 01:13:0{i} web sshd[811]: Failed password for root from 203.0.113.7 port 5{i}22 ssh2\n"


def test_detects_bruteforce_once_per_ip(tmp_path):
    log = tmp_path / "auth.log"
    log.write_text("".join(FAIL.format(i=i) for i in range(6)))
    watch = LogWatch(str(log), threshold=5, window_seconds=300)
    events = watch.scan(now=1000)
    assert len(events) == 1 and "203.0.113.7" in events[0].message
    with open(log, "a") as fh:
        fh.write(FAIL.format(i=7))
    assert watch.scan(now=1010) == []  # already alerted for this IP


def test_below_threshold_and_window_expiry(tmp_path):
    log = tmp_path / "auth.log"
    log.write_text("".join(FAIL.format(i=i) for i in range(3)))
    watch = LogWatch(str(log), threshold=5, window_seconds=60)
    assert watch.scan(now=0) == []
    with open(log, "a") as fh:
        fh.write("".join(FAIL.format(i=i) for i in range(3)))
    assert watch.scan(now=120) == []  # first three aged out of the window
    assert watch.counts() == {"203.0.113.7": 3}


def test_invalid_user_pattern(tmp_path):
    log = tmp_path / "auth.log"
    log.write_text("sshd[1]: Failed password for invalid user admin from 198.51.100.4 port 22 ssh2\n" * 5)
    events = LogWatch(str(log), threshold=5).scan(now=0)
    assert "198.51.100.4" in events[0].message


def test_only_reads_new_lines_and_handles_rotation(tmp_path):
    log = tmp_path / "syslog"
    log.write_text("kernel: error one\n")
    watch = LogWatch(str(log), pattern="errors", threshold=3)
    watch.scan(now=0)
    assert watch.counts() == {"errors": 1}
    os.rename(log, tmp_path / "syslog.1")
    log.write_text("app: fatal two\napp: panic three\n")
    events = watch.scan(now=1)
    assert watch.counts() == {"errors": 3} and len(events) == 1


def test_partial_line_is_kept_for_next_scan(tmp_path):
    log = tmp_path / "auth.log"
    log.write_text("Failed password for root from 10.0.0.9 por")
    watch = LogWatch(str(log), threshold=1)
    assert watch.scan(now=0) == []
    with open(log, "a") as fh:
        fh.write("t 22 ssh2\n")
    assert len(watch.scan(now=1)) == 1


def test_missing_file_is_ignored(tmp_path):
    assert LogWatch(str(tmp_path / "nope.log")).scan() == []
