from config import QUOTA_FILESYSTEM
from utils.shell import run


def _parse_size_to_kb(size: str) -> int:
    """Parse a human size string ('1G', '500M', '100K') into 1-KB blocks for setquota."""
    s = size.upper().strip()
    if s.endswith("G"):
        return int(float(s[:-1]) * 1024 * 1024)
    if s.endswith("M"):
        return int(float(s[:-1]) * 1024)
    if s.endswith("K"):
        return int(float(s[:-1]))
    return int(s)


def set_quota(username: str, soft: str, filesystem: str = QUOTA_FILESYSTEM):
    """Set disk quota for a user. Hard limit = soft + 20%."""
    soft_kb = _parse_size_to_kb(soft)
    hard_kb = int(soft_kb * 1.2)
    run([
        "sudo", "setquota", "-u", username,
        str(soft_kb), str(hard_kb), "0", "0", filesystem,
    ])


def remove_quota(username: str, filesystem: str = QUOTA_FILESYSTEM):
    """Remove disk quota for a user."""
    run(
        ["sudo", "setquota", "-u", username, "0", "0", "0", "0", filesystem],
        check=False,
    )
