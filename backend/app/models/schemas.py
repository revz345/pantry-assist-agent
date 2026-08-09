from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, Relationship, SQLModel


class Unit(str, Enum):
    GRAMS = "g"
    KILOGRAMS = "kg"
    PIECES = "pcs"
    LITERS = "l"
    MILLILITERS = "ml"
    CUPS = "cup"
    TBSP = "tbsp"
    TSP = "tsp"


class MealType(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    SNACK = "snack"
    DINNER = "dinner"


class ItemBase(SQLModel):
    name: str = Field(index=True, max_length=100)
    quantity: float = Field(default=1.0, ge=0)
    unit: Unit = Field(default=Unit.PIECES)
    category: str | None = Field(default=None, index=True, max_length=60)
    expiry_date: date | None = Field(default=None, index=True)
    barcode: str | None = Field(default=None, index=True, max_length=50)
    photo_url: str | None = Field(default=None, max_length=500)
    location_id: int | None = Field(default=None, foreign_key="location.id")


class Item(ItemBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    location: Optional["Location"] = Relationship(back_populates="items")


class ItemCreate(ItemBase):
    pass


class ItemUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=100)
    quantity: float | None = Field(default=None, ge=0)
    unit: Unit | None = None
    category: str | None = Field(default=None, max_length=60)
    expiry_date: date | None = None
    barcode: str | None = Field(default=None, max_length=50)
    photo_url: str | None = Field(default=None, max_length=500)
    location_id: int | None = None


class ItemRead(ItemBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LocationBase(SQLModel):
    name: str = Field(index=True, max_length=50, unique=True)
    description: str | None = Field(default=None, max_length=200)


class Location(LocationBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    items: list[Item] = Relationship(back_populates="location")


class LocationCreate(LocationBase):
    pass


class LocationUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=200)


class LocationRead(LocationBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class RecipeSuggestionBase(SQLModel):
    title: str
    description: str | None = None
    ingredients: list[str]
    instructions: list[str]
    estimated_time_minutes: int | None = None
    servings: int | None = None
    meal_type: MealType | None = None


class RecipeSuggestion(RecipeSuggestionBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source_inventory_snapshot: str | None = None  # JSON of items used
    ingredients: list[str] = Field(default=[], sa_column=Column(JSON))
    instructions: list[str] = Field(default=[], sa_column=Column(JSON))


class RecipeSuggestionRead(RecipeSuggestionBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class RecipeFeedbackBase(SQLModel):
    recipe_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)
    accepted: bool = False


class RecipeFeedback(RecipeFeedbackBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RecipeFeedbackCreate(RecipeFeedbackBase):
    pass


class RecipeFeedbackRead(RecipeFeedbackBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
