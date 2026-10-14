
"""知识库相关模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer, BigInteger, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from core.database import Base


class KnowledgeBase(Base):
    """知识库模型"""
    __tablename__ = "knowledge_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    document_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base):
    """文档模型"""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50))
    file_size = Column(BigInteger)
    file_path = Column(String(500))
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    chunk_count = Column(Integer, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    user = relationship("User", back_populates="documents")
    assets = relationship("DocumentAsset", back_populates="document", cascade="all, delete-orphan")
    provenance = relationship("DocumentChunkProvenance", back_populates="document", cascade="all, delete-orphan")


class DocumentAsset(Base):
    """Parser-provided objects; locators never come from generated prose."""
    __tablename__ = "document_assets"

    id = Column(String(64), primary_key=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version = Column(String(64), nullable=False)
    asset_type = Column(String(32), nullable=False)
    content = Column(Text, nullable=True)
    file_path = Column(String(1000), nullable=True)
    media_type = Column(String(100), nullable=True)
    locator = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    document = relationship("Document", back_populates="assets")


class DocumentChunkProvenance(Base):
    """Associates the existing seven-field vector rows with document UUIDs."""
    __tablename__ = "document_chunk_provenance"
    __table_args__ = (UniqueConstraint("collection_name", "chunk_id", name="uq_chunk_provenance_collection_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version = Column(String(64), nullable=False)
    collection_name = Column(String(255), nullable=False, index=True)
    chunk_id = Column(String(64), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text_start = Column(Integer, nullable=False)
    text_end = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    locators = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    asset_ids = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    document = relationship("Document", back_populates="provenance")
