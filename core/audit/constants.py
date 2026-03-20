class AuditAction:
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    READ = "READ"


class AuditModule:
    AUTH = "AUTH"
    USER = "USER"
    BILLING = "BILLING"
    TENANT = "TENANT"
    SYSTEM = "SYSTEM"
