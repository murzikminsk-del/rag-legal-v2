class LLMError(Exception):
    def __init__(self, message: str, code: str = "llm_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class LLMRateLimitError(LLMError):
    def __init__(self, message: str = "LLM rate limit exceeded") -> None:
        super().__init__(message, code="llm_rate_limit")


class LLMTimeoutError(LLMError):
    def __init__(self, message: str = "LLM request timed out") -> None:
        super().__init__(message, code="llm_timeout")


class LLMAuthError(LLMError):
    def __init__(self, message: str = "LLM authentication failed") -> None:
        super().__init__(message, code="llm_auth")