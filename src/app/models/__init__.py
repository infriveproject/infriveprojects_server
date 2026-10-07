from src.app.models.user import User  # must be imported before UserProjectRole
from src.app.models.department import Department
from src.app.models.location import Location
from src.app.models.form_record import FormRecord
from src.app.models.form_record_location import FormRecordLocation
from src.app.models.form_record_rating import FormRecordRating
from src.app.models.rating_comment_preset import RatingCommentPreset
from src.app.models.form_type import FormType
from src.app.models.permission import (
    CategoryPermission,
    FormTypePermission,
    ProjectMember,
    ProjectRole,
    Role,
    RoleSet,  # must be imported before Stage (Stage.role_set_id FK)
    RoleSetRole,
    StagePermission,
    UserProjectRole,
)
from src.app.models.stage import Stage
from src.app.models.stage_location import StageLocation
from src.app.models.stage_form_type import StageFormType
from src.app.models.form_action import FormAction
from src.app.models.workflow_assignment import WorkflowAssignment
from src.app.models.group import Group
from src.app.models.my_document import MyDocument, MyDocumentFolder

__all__ = [
    "User",
    "Department",
    "Location",
    "Stage",
    "StageLocation",
    "FormType",
    "StageFormType",
    "FormRecord",
    "FormRecordLocation",
    "FormRecordRating",
    "RatingCommentPreset",
    "FormAction",
    "WorkflowAssignment",
    "StagePermission",
    "FormTypePermission",
    "CategoryPermission",
    "Role",
    "RoleSet",
    "RoleSetRole",
    "ProjectRole",
    "ProjectMember",
    "UserProjectRole",
    "Group",
    "MyDocument",
    "MyDocumentFolder",
]
