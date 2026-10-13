"""updater 의 버전 비교 로직 테스트 (네트워크 불필요)."""
from updater import is_newer, parse_version

assert parse_version("v1.2.3") == (1, 2, 3)
assert parse_version("1.0") == (1, 0)
assert parse_version("abc") is None
assert is_newer("v1.0.1", "1.0.0")
assert is_newer("v1.10.0", "1.9.9")      # 문자열 비교가 아니라 숫자 비교
assert not is_newer("v1.0.0", "1.0.0")
assert not is_newer("v0.9.0", "1.0.0")
assert not is_newer("latest", "1.0.0")   # 해석 못 하면 업데이트 안 함
print("updater tests OK")
