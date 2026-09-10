def public_api(x: int) -> int:
    return _helper(x, 2)

def _helper(x: int, factor: int) -> int:
    return x * factor
