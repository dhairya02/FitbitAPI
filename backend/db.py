"""
Database models and utilities for Fitbit token storage.
Now supports multiple participants.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Union, List
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from backend.config import DATABASE_URL

# Get logger
logger = logging.getLogger("fitbit_app.db")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Participant(Base):
    """
    Model for storing participant information.
    Each participant connects their own Fitbit account using shared app credentials.
    """
    __tablename__ = "participants"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    participant_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to tokens
    tokens = relationship("FitbitToken", back_populates="participant", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<Participant(id={self.id}, participant_id='{self.participant_id}', name='{self.name}')>"


class FitbitToken(Base):
    """
    Model for storing Fitbit OAuth tokens.
    Each token is associated with a participant.
    Note: A Fitbit account can be connected to multiple participants if needed.
    """
    __tablename__ = "fitbit_tokens"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key to participant
    participant_id = Column(String, ForeignKey("participants.participant_id"), nullable=False, index=True)
    
    # Fitbit user identifier (removed UNIQUE constraint to allow sharing)
    fitbit_user_id = Column(String, nullable=False)
    
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
    
    # Relationship
    participant = relationship("Participant", back_populates="tokens")
    
    def __repr__(self) -> str:
        return (
            f"<FitbitToken(id={self.id}, "
            f"participant_id='{self.participant_id}', "
            f"fitbit_user_id='{self.fitbit_user_id}')>"
        )


# Create index for faster lookups
Index('idx_participant_token', FitbitToken.participant_id)


def init_db() -> None:
    """
    Initialize the database by creating all tables.
    Safe to call multiple times.
    """
    logger.info("Initializing database")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        raise


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


# ============================================================================
# Participant Management
# ============================================================================

def create_participant(session: Session, participant_id: str, name: str = None, 
                       email: str = None, notes: str = None) -> Participant:
    """
    Create a new participant.
    
    Args:
        session: SQLAlchemy session
        participant_id: Unique identifier for the participant
        name: Optional display name
        email: Optional email
        notes: Optional notes
        
    Returns:
        Created Participant instance
    """
    logger.info(f"Creating participant: {participant_id}")
    
    # Check if participant already exists
    existing = session.query(Participant).filter_by(participant_id=participant_id).first()
    if existing:
        raise ValueError(f"Participant '{participant_id}' already exists")
    
    participant = Participant(
        participant_id=participant_id,
        name=name,
        email=email,
        notes=notes,
    )
    session.add(participant)
    session.commit()
    logger.info(f"Participant created: {participant_id}")
    return participant


def get_participant(session: Session, participant_id: str) -> Optional[Participant]:
    """Get a participant by ID."""
    return session.query(Participant).filter_by(participant_id=participant_id).first()


def get_all_participants(session: Session) -> List[Participant]:
    """Get all participants ordered by creation date."""
    return session.query(Participant).order_by(Participant.created_at).all()


def update_participant(session: Session, participant_id: str, **kwargs) -> Participant:
    """Update participant information."""
    participant = get_participant(session, participant_id)
    if not participant:
        raise ValueError(f"Participant '{participant_id}' not found")
    
    for key, value in kwargs.items():
        if hasattr(participant, key):
            setattr(participant, key, value)
    
    participant.updated_at = datetime.utcnow()
    session.commit()
    logger.info(f"Participant updated: {participant_id}")
    return participant


def delete_participant(session: Session, participant_id: str) -> None:
    """Delete a participant and all associated tokens."""
    participant = get_participant(session, participant_id)
    if participant:
        session.delete(participant)
        session.commit()
        logger.info(f"Participant deleted: {participant_id}")


# ============================================================================
# Token Management (Multi-Participant)
# ============================================================================

def get_token_for_participant(session: Session, participant_id: str) -> Optional[FitbitToken]:
    """
    Get the Fitbit token for a specific participant.
    
    Args:
        session: SQLAlchemy session
        participant_id: Participant identifier
        
    Returns:
        FitbitToken if exists, None otherwise
    """
    return session.query(FitbitToken).filter_by(participant_id=participant_id).first()


def upsert_token_for_participant(session: Session, participant_id: str, 
                                  token_dict: Dict[str, Any]) -> FitbitToken:
    """
    Insert or update token for a specific participant.
    
    Args:
        session: SQLAlchemy session
        participant_id: Participant identifier
        token_dict: Token dictionary from Fitbit OAuth
        
    Returns:
        Created or updated FitbitToken
    """
    # Ensure participant exists
    participant = get_participant(session, participant_id)
    if not participant:
        raise ValueError(f"Participant '{participant_id}' does not exist. Create participant first.")
    
    existing_token = get_token_for_participant(session, participant_id)
    
    # Extract and normalize values
    access_token = token_dict["access_token"]
    refresh_token = token_dict["refresh_token"]
    expires_at = float(token_dict["expires_at"])
    fitbit_user_id = token_dict.get("user_id", "unknown")
    scope = normalize_scope(token_dict.get("scope", ""))
    token_type = token_dict.get("token_type", "Bearer")
    
    try:
        if existing_token:
            logger.info(f"Updating token for participant: {participant_id}, Fitbit user: {fitbit_user_id}")
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
            logger.info(f"Creating token for participant: {participant_id}, Fitbit user: {fitbit_user_id}")
            new_token = FitbitToken(
                participant_id=participant_id,
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
    except Exception as e:
        logger.error(f"Failed to upsert token for {participant_id}: {e}", exc_info=True)
        session.rollback()
        raise


def disconnect_participant(session: Session, participant_id: str) -> bool:
    """
    Disconnect a participant's Fitbit account (delete their token).
    
    Returns:
        True if token was deleted, False if no token existed
    """
    token = get_token_for_participant(session, participant_id)
    if token:
        session.delete(token)
        session.commit()
        logger.info(f"Disconnected Fitbit for participant: {participant_id}")
        return True
    return False


# ============================================================================
# Backward Compatibility (for single-user code)
# ============================================================================

def get_single_token(session: Session) -> Optional[FitbitToken]:
    """
    Retrieve the first token (backward compatibility).
    For multi-user apps, use get_token_for_participant instead.
    """
    return session.query(FitbitToken).first()


def upsert_single_token(session: Session, token_dict: Dict[str, Any]) -> FitbitToken:
    """
    Upsert token for default participant (backward compatibility).
    """
    # Ensure "default" participant exists
    participant = get_participant(session, "default")
    if not participant:
        participant = create_participant(session, "default", name="Default User")
    
    return upsert_token_for_participant(session, "default", token_dict)
