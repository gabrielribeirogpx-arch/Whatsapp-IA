from backend.app.models.conversation import Conversation
from backend.app.models.contact import Contact
from backend.app.models.message import Message
from backend.app.models.tenant import AIConfig, Tenant
from backend.app.models.product import Product
from backend.app.models.knowledge_base import KnowledgeBase

__all__ = ["Tenant", "AIConfig", "Conversation", "Contact", "Message", "Product", "KnowledgeBase"]
