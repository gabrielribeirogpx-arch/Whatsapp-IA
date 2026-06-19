class ToolRegistryError(Exception):
    error_code = "tool_registry_error"

class ToolNotFound(ToolRegistryError):
    error_code = "tool_not_found"

class ToolNotAllowed(ToolRegistryError):
    error_code = "tool_not_allowed"

class ToolExecutionError(ToolRegistryError):
    error_code = "tool_execution_error"

class ToolBudgetExceeded(ToolRegistryError):
    error_code = "budget_exceeded"

class ToolValidationError(ToolRegistryError):
    error_code = "validation_error"
