from enum import Enum


class ProviderTypeEnum(str, Enum):
    META_CLOUD = "meta_cloud"
    BSP_360DIALOG = "bsp_360dialog"
    TWILIO = "twilio"


class TemplateStatusEnum(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"


class TemplateCategoryEnum(str, Enum):
    UTILITY = "utility"
    MARKETING = "marketing"
    AUTHENTICATION = "authentication"
