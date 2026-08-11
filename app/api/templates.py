from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, require_domain_auth
from app.schemas import TemplateCreate, TemplateOut, TemplateWeekdaysPatch
from app.services import templates as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_domain_auth)])


@router.post("/templates", status_code=status.HTTP_201_CREATED, response_model=TemplateOut)
def create_template(data: TemplateCreate, session: DbSession) -> TemplateOut:
    return svc.create_template(session, data)


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(session: DbSession) -> list[TemplateOut]:
    return svc.list_templates(session)


@router.get("/templates/{template_id}", response_model=TemplateOut)
def get_template(template_id: int, session: DbSession) -> TemplateOut:
    return svc.get_template(session, template_id)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(template_id: int, data: TemplateCreate, session: DbSession) -> TemplateOut:
    return svc.update_template(session, template_id, data)


@router.patch("/templates/{template_id}/weekdays", response_model=TemplateOut)
def set_template_weekdays(
    template_id: int, data: TemplateWeekdaysPatch, session: DbSession
) -> TemplateOut:
    """只改排程（F80）——課表列表上排星期時不必整份送回。"""
    return svc.set_weekdays(session, template_id, data.weekdays)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, session: DbSession) -> None:
    svc.delete_template(session, template_id)
