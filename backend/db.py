"""
Database models and utilities for Fitbit token storage.
Uses SQLAlchemy ORM with SQLite.
"""
from datetime import datetime
from typing import Optional, Dict, Any, Union
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from backend.config import DATABASE_URL

# SQLAlchemy setup
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class FitbitToken(Base):
    """
    Model for storing Fitbit OAuth tokens.
    
    Designed for single-user now, but structured for future multi-user support
    via the participant_id field.
    """
    __tablename__ = "fitbit_tokens"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # For future multi-user support; currently always "default"
    participant_id = Column(String, nullable=True, default="default")
    
    # Fitbit user identifier
    fitbit_user_id = Column(String, nullable=False, unique=True)
    
    # OAuth tokens
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    expires_at = Column(Float, nullable=False)  # Unix timestamp
    
    # Additional token metadata
    scope = Column(String, nullable=True)
    token_type = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self) -> str:
        return (
            f"<FitbitToken(id={self.id}, "
            f"participant_id='{self.participant_id}', "
            f"fitbit_user_id='{self.fitbit_user_id}')>"
        )


def init_db() -> None:
    """
    Initialize the database by creating all tables.
    Safe to call multiple times.
    """
    Base.metadata.create_all(bind=engine)


def get_single_token(session: Session) -> Optional[FitbitToken]:
    """
    Retrieve the single token for the default user.
    
    Args:
        session: SQLAlchemy session
        
    Returns:
        FitbitToken instance if exists, None otherwise
    """
    return session.query(FitbitToken).first()


def normalize_scope(scope: Union[str, list, tuple]) -> str:
    """
    Normalize scope to a space-separated string.
    
    Args:
        scope: Scope as string, list, or tuple
        
    Returns:
        Space-separated scope string
    """
    if isinstance(scope, (list, tuple)):
        return " ".join(scope)
    return str(scope)


def upsert_single_token(session: Session, token_dict: Dict[str, Any]) -> FitbitToken:
    """
    Insert or update the single token for the default user.
    
    For single-user mode, we maintain at most one token row.
    If a token exists, update it; otherwise, create a new one.
    
    Args:
        session: SQLAlchemy session
        token_dict: Dictionary containing token information with keys:
            - access_token (required)
            - refresh_token (required)
            - expires_at (required)
            - user_id (optional, will be used as fitbit_user_id)
            - scope (optional)
            - token_type (optional)
            
    Returns:
        The created or updated FitbitToken instance
    """
    existing_token = get_single_token(session)
    
    # Extract and normalize values
    access_token = token_dict["access_token"]
    refresh_token = token_dict["refresh_token"]
    expires_at = float(token_dict["expires_at"])
    fitbit_user_id = token_dict.get("user_id", "unknown")
    scope = normalize_scope(token_dict.get("scope", ""))
    token_type = token_dict.get("token_type", "Bearer")
    
    if existing_token:
        # Update existing token
        existing_token.participant_id = "default"
        existing_token.fitbit_user_id = fitbit_user_id
        existing_token.access_token = access_token
        existing_token.refresh_token = refresh_token
        existing_token.expires_at = expires_at
        existing_token.scope = scope
        existing_token.token_type = token_type
        existing_token.updated_at = datetime.utcnow()
        session.commit()
        return existing_token
    else:
        # Create new token
        new_token = FitbitToken(
            participant_id="default",
            fitbit_user_id=fitbit_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        )
        session.add(new_token)
        session.commit()
        return new_token

