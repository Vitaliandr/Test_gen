from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

#из этой схемы делается company.schema.json


class Person(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    role: str = Field(min_length=3, max_length=100)
    level: Literal["ceo", "head", "staff"]
    bio: str = Field(min_length=40, max_length=700)


class Scenario(BaseModel):
    title: str = Field(min_length=5, max_length=120)
    situation: str = Field(min_length=30, max_length=400)
    how_it_helps: str = Field(min_length=30, max_length=500)
    result: str = Field(min_length=20, max_length=300)


class Product(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    summary: str = Field(min_length=30, max_length=600)
    inputs: list[str] = Field(min_length=2, max_length=6)
    process: list[str] = Field(min_length=3, max_length=6)
    outputs: list[str] = Field(min_length=2, max_length=6)
    limitations: list[str] = Field(min_length=2, max_length=6)
    scenarios: list[Scenario] = Field(min_length=3, max_length=4)


class FaqItem(BaseModel):
    question: str = Field(min_length=10, max_length=200)
    answer: str = Field(min_length=20, max_length=800)


class CompanyContent(BaseModel):
    # то что пишет модель
    brand: str = Field(min_length=2, max_length=60)
    legal_name: str = Field(min_length=4, max_length=100)
    founding_year: int = Field(ge=1990, le=2100)
    employee_count: int = Field(ge=3, le=500)
    tagline: str = Field(min_length=10, max_length=140)
    value_proposition: str = Field(min_length=30, max_length=500)
    advantages: list[str] = Field(min_length=3, max_length=5)
    history: str = Field(min_length=100, max_length=1500)
    specialization: str = Field(min_length=40, max_length=800)
    audience: str = Field(min_length=30, max_length=600)
    client_problem: str = Field(min_length=30, max_length=600)
    product: Product
    faq: list[FaqItem] = Field(min_length=5, max_length=5)
    #ceo, 2 head и минимум 2 staff, по ТЗ от 5 человек
    people: list[Person] = Field(min_length=5, max_length=12)

    @model_validator(mode="after")
    def check_people(self) -> "CompanyContent":
        levels = [p.level for p in self.people]
        if levels.count("ceo") != 1 or levels.count("head") != 2 or levels.count("staff") < 2:
            raise ValueError("people: нужен 1 ceo, 2 head и минимум 2 staff")
        return self


class Contacts(BaseModel):
    city: str
    # 5 или 6 цифр смотря по стране, это в проверках
    postal_code: str = Field(pattern=r"^\d{4,6}$")
    street: str
    phone: str
    email: str


class Company(CompanyContent):
    country: str
    direction: str
    service_type: str
    scale: Literal["small", "medium"]
    language: Literal["ru", "de"]
    contacts: Contacts
    #разделов может и не быть
    sections: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_sections(self) -> "Company":
        # импорт тут, а то циклический
        from sitegen.aspects import registry

        fixed = {}
        for key, value in self.sections.items():
            aspect = registry.find(key)
            if aspect is None:
                raise ValueError(f"sections: неизвестный раздел {key}")
            fixed[key] = aspect.model.model_validate(value).model_dump()
        self.sections = fixed
        return self
