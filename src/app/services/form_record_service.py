import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.models.form_record import FormRecord
from src.app.models.form_type import FormType
from src.app.models.form_action import FormAction
from src.app.models.form_record_rating import FormRecordRating
from src.app.models.stage import Stage
from src.app.services.stage_service import StageService
from src.app.schemas.form_record import (
    FormRecordCreate,
    FormRecordResponse,
    FormRecordUpdate,
)
from src.app.storage.minio_storage import storage_service
from src.app.services.rating_comment_preset_service import RatingCommentPresetService
from src.app.services.workflow_assignment_service import WorkflowAssignmentService
from transitions import Machine

class RecordContext:
    def __init__(self, state):
        self.state = state


logger = logging.getLogger(__name__)


# Triggers that are a judgement of quality and therefore demand a score and
# a justification. A cancel/reject is a rejection, not a grade — forcing a
# rating there would make cancelling a record impossible. The UI mirrors this
# set; this copy is the one that is enforced.
RATEABLE_TRIGGERS = frozenset({"submit", "verify"})


class FormRecordService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _new_id() -> str:
        return f"rec_{uuid.uuid4().hex[:12]}"



    @staticmethod
    def _abbrev(form_name: str) -> str:
        words = form_name.upper().split()
        if len(words) == 1:
            return words[0][:6]
        return "".join(w[0] for w in words[:5])

    async def _next_docname(self, form_type_id: str, form_name: str) -> str:
        result = await self.db.execute(
            select(func.count()).where(FormRecord.form_type_id == form_type_id)
        )
        count = result.scalar() or 0
        return f"{self._abbrev(form_name)}-{count + 1:05d}"

    def _parse(self, record: FormRecord, populated_data: Optional[dict] = None) -> FormRecordResponse:
        parsed_data = populated_data if populated_data is not None else record.data
        if parsed_data is None:
            parsed_data = {}
        return FormRecordResponse.model_validate({
            "record_id": record.record_id,
            "form_type_id": record.form_type_id,
            "stage_id": record.stage_id,
            "project_stage_id": record.project_stage_id,
            "docname": record.docname,
            "status": record.status,
            "assigned_role": record.assigned_role,
            "assigned_to": record.assigned_to,
            "assigned_at": record.assigned_at,
            "data": parsed_data,
            "schema_snapshot": record.schema_snapshot,
            "form_version": record.form_version,
            "amended_from": record.amended_from,
            "parent_record_id": record.parent_record_id,
            "parent_form_type_id": record.parent_form_type_id,
            "parent_field_name": record.parent_field_name,
            "submitted_by": record.submitted_by,
            "submitted_at": record.submitted_at,
            "created_by": record.created_by,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        })

    async def _get_form_type_by_name(self, form_name: str) -> Optional[FormType]:
        result = await self.db.execute(
            select(FormType).where(FormType.form_name == form_name)
        )
        return result.scalars().first()

    async def _save_child_records(
        self,
        parent_record: FormRecord,
        data: dict,
        schema_fields: list,
        created_by: str,
        is_update: bool = False
    ) -> dict:
        """
        Recursively process Table and Link fields to create/update independent child records,
        and return the parent's data dict with children fully populated (with record_id and docname).
        """
        cleaned_data = {}
        
        # If it's an update, fetch all existing children for this parent
        existing_children = []
        if is_update:
            result = await self.db.execute(
                select(FormRecord).where(FormRecord.parent_record_id == parent_record.record_id)
            )
            existing_children = result.scalars().all()
            
        # Group existing children by field name
        existing_by_field = {}
        for child in existing_children:
            existing_by_field.setdefault(child.parent_field_name, []).append(child)

        for field in schema_fields:
            fieldname = field.get("fieldname")
            fieldtype = field.get("fieldtype")
            options = field.get("options")
            
            if not fieldname:
                continue
                
            val = data.get(fieldname)
            
            if fieldtype in ("Table", "Table MultiSelect") and options:
                # Resolve child FormType
                child_ft = await self._get_form_type_by_name(options)
                if not child_ft:
                    cleaned_data[fieldname] = []
                    continue
                
                new_rows = val if isinstance(val, list) else []
                processed_rows = []
                
                # List of existing child records for this field
                field_existing = existing_by_field.get(fieldname, [])
                field_existing_by_id = {c.record_id: c for c in field_existing}
                field_existing_by_docname = {c.docname: c for c in field_existing if c.docname}
                
                kept_ids = set()
                
                for row in new_rows:
                    if not isinstance(row, dict):
                        continue
                        
                    # Check if this row matches an existing child record
                    child_id = row.get("record_id") or row.get("name")
                    child_docname = row.get("docname")
                    
                    matched_child = None
                    if child_id and child_id in field_existing_by_id:
                        matched_child = field_existing_by_id[child_id]
                    elif child_docname and child_docname in field_existing_by_docname:
                        matched_child = field_existing_by_docname[child_docname]
                        
                    if matched_child:
                        # Update existing child
                        kept_ids.add(matched_child.record_id)
                        
                        # Process nested children first
                        child_schema = child_ft.schema_reference or {}
                        child_fields = child_schema.get("fields", [])
                        processed_row_data = await self._save_child_records(
                            parent_record=matched_child,
                            data=row,
                            schema_fields=child_fields,
                            created_by=created_by,
                            is_update=True
                        )
                        # Process attachments for the child row
                        processed_row_data = self._process_attachments(child_ft, processed_row_data, matched_child.record_id)
                        matched_child.data = processed_row_data
                        matched_child.updated_at = datetime.now(timezone.utc)
                        
                        processed_row_data["record_id"] = matched_child.record_id
                        processed_row_data["docname"] = matched_child.docname
                        processed_rows.append(processed_row_data)
                    else:
                        # Create new child
                        child_record_id = self._new_id()
                        child_docname = await self._next_docname(child_ft.form_type_id, child_ft.form_name)
                        
                        new_child = FormRecord(
                            record_id=child_record_id,
                            form_type_id=child_ft.form_type_id,
                            stage_id=parent_record.stage_id,
                            project_stage_id=parent_record.project_stage_id,
                            docname=child_docname,
                            status="Draft",
                            assigned_role="worker",
                            assigned_to=created_by,
                            assigned_at=datetime.now(timezone.utc),
                            created_by=created_by,
                            form_version=child_ft.version,
                            schema_snapshot=child_ft.schema_reference,
                            parent_record_id=parent_record.record_id,
                            parent_form_type_id=parent_record.form_type_id,
                            parent_field_name=fieldname,
                        )
                        self.db.add(new_child)
                        
                        # Process nested children
                        child_schema = child_ft.schema_reference or {}
                        child_fields = child_schema.get("fields", [])
                        processed_row_data = await self._save_child_records(
                            parent_record=new_child,
                            data=row,
                            schema_fields=child_fields,
                            created_by=created_by,
                            is_update=False
                        )
                        # Process attachments for the child row
                        processed_row_data = self._process_attachments(child_ft, processed_row_data, child_record_id)
                        new_child.data = processed_row_data
                        
                        processed_row_data["record_id"] = child_record_id
                        processed_row_data["docname"] = child_docname
                        processed_rows.append(processed_row_data)
                        
                # Delete any existing children that were not in the new list
                for c in field_existing:
                    if c.record_id not in kept_ids:
                        await self.db.delete(c)
                
                cleaned_data[fieldname] = processed_rows
                        
            elif fieldtype in ("Link", "Dynamic Link") and options:
                child_ft = await self._get_form_type_by_name(options)
                if not child_ft:
                    cleaned_data[fieldname] = val
                    continue
                    
                if isinstance(val, dict):
                    # Inline creation of a new child record!
                    child_record_id = self._new_id()
                    child_docname = await self._next_docname(child_ft.form_type_id, child_ft.form_name)
                    
                    new_child = FormRecord(
                        record_id=child_record_id,
                        form_type_id=child_ft.form_type_id,
                        stage_id=parent_record.stage_id,
                        project_stage_id=parent_record.project_stage_id,
                        docname=child_docname,
                        status="Draft",
                        assigned_role="worker",
                        assigned_to=created_by,
                        assigned_at=datetime.now(timezone.utc),
                        created_by=created_by,
                        form_version=child_ft.version,
                        schema_snapshot=child_ft.schema_reference,
                        parent_record_id=parent_record.record_id,
                        parent_form_type_id=parent_record.form_type_id,
                        parent_field_name=fieldname,
                    )
                    self.db.add(new_child)
                    
                    child_schema = child_ft.schema_reference or {}
                    child_fields = child_schema.get("fields", [])
                    processed_child_data = await self._save_child_records(
                        parent_record=new_child,
                        data=val,
                        schema_fields=child_fields,
                        created_by=created_by,
                        is_update=False
                    )
                    # Process attachments for the child row
                    processed_child_data = self._process_attachments(child_ft, processed_child_data, child_record_id)
                    new_child.data = processed_child_data
                    
                    # Parent field now points to the new child's docname
                    cleaned_data[fieldname] = child_docname
                else:
                    cleaned_data[fieldname] = val
                    # If it's an existing docname string, we can update the existing record
                    if isinstance(val, str) and val:
                        result = await self.db.execute(
                            select(FormRecord).where(
                                FormRecord.docname == val,
                                FormRecord.form_type_id == child_ft.form_type_id
                            )
                        )
                        existing_child = result.scalars().first()
                        if existing_child:
                            same_project_only = field.get("same_project_only") is not False
                            if (
                                same_project_only
                                and parent_record.project_stage_id
                                and existing_child.project_stage_id
                                and existing_child.project_stage_id != parent_record.project_stage_id
                            ):
                                raise ValueError(
                                    f"'{val}' belongs to a different project and cannot be linked from '{fieldname}'"
                                )
                            existing_child.parent_record_id = parent_record.record_id
                            existing_child.parent_form_type_id = parent_record.form_type_id
                            existing_child.parent_field_name = fieldname
            else:
                cleaned_data[fieldname] = val
                
        return cleaned_data

    async def _populate_child_records(self, record: FormRecord) -> dict:
        """
        Recursively query and populate child records into the record's data dict.
        """
        if not record:
            return {}
            
        data = dict(record.data) if record.data else {}
        
        # Fetch all child records of this record
        result = await self.db.execute(
            select(FormRecord).where(FormRecord.parent_record_id == record.record_id)
        )
        children = result.scalars().all()
        
        if not children:
            return data
            
        # Group children by parent_field_name
        children_by_field = {}
        for child in children:
            children_by_field.setdefault(child.parent_field_name, []).append(child)
            
        # Resolve parent form type schema to see field types
        ft = await self.db.get(FormType, record.form_type_id)
        schema = ft.schema_reference if ft else {}
        fields = schema.get("fields", []) if isinstance(schema, dict) else []
        field_types = {f.get("fieldname"): f.get("fieldtype") for f in fields if f.get("fieldname")}
        
        for fieldname, child_list in children_by_field.items():
            fieldtype = field_types.get(fieldname)
            
            if fieldtype in ("Table", "Table MultiSelect"):
                populated_rows = []
                for child in child_list:
                    # Recursively populate child's own children
                    child_data = await self._populate_child_records(child)
                    # Add child record identifiers for reference in frontend/updates
                    child_data["record_id"] = child.record_id
                    child_data["docname"] = child.docname
                    populated_rows.append(child_data)
                data[fieldname] = populated_rows
            elif fieldtype in ("Link", "Dynamic Link"):
                if child_list:
                    data[fieldname] = child_list[0].docname
                    
        return data

    def _strip_child_records(self, data: dict, schema_fields: list) -> dict:
        """
        Strip child Table and Link dictionary values from data dictionary
        before saving to DB, keeping only references or empty values.
        """
        stripped_data = dict(data)
        for field in schema_fields:
            fieldname = field.get("fieldname")
            fieldtype = field.get("fieldtype")
            if not fieldname or fieldname not in stripped_data:
                continue
                
            if fieldtype in ("Table", "Table MultiSelect"):
                stripped_data[fieldname] = []
        return stripped_data

    def _get_attach_field(self, ft: FormType, field_name: str) -> Optional[dict]:
        """Look up a field definition by name; return it only if it is an Attach type."""
        if not ft.schema_reference:
            logger.error(f"FormType {ft.form_type_id} has no schema_reference")
            return None
        schema_reference = ft.schema_reference
        for field in schema_reference.get("fields", []):
            logger.info(f"Field {field}")
            if field.get("fieldname") == field_name:
                field_type = field.get("fieldtype") or ""
                if field_type in ("Attach", "Attach Image"):
                    logger.info(f"Attach field found: {field}")
                    return field
        return None

    def _build_minio_path(self, ft: FormType, field: dict, filename: str, record_id: str) -> str:
        """Build the canonical MinIO path: form_type_id/record_id/field_id/filename."""
        field_id = field.get("fieldname")
        return f"{ft.form_type_id}/{record_id}/{field_id}/{filename}"

    def _process_attachments(self, ft: FormType, data: dict, record_id: str) -> dict:
        """Ensure attachment fields contain the full path."""
        if not data or not ft.schema_reference:
            return data

        schema_ref = ft.schema_reference
        if not isinstance(schema_ref, dict):
            return data

        for field in schema_ref.get("fields", []):
            field_type = field.get("fieldtype") or ""
            if field_type not in ("Attach", "Attach Image"):
                continue
            field_name = field.get("fieldname")
            if not field_name or field_name not in data:
                continue
            value = data[field_name]
            if not value:
                continue

            # Normalize value to a list of strings
            import json
            normalized_list = []
            if isinstance(value, str):
                # Check if it looks like a JSON array
                if value.strip().startswith('[') and value.strip().endswith(']'):
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            normalized_list = parsed
                        else:
                            normalized_list = [value]
                    except Exception:
                        normalized_list = [value]
                else:
                    normalized_list = [value]
            elif isinstance(value, list):
                normalized_list = value
            else:
                normalized_list = [str(value)]

            processed_list = []
            for item in normalized_list:
                if not item or not isinstance(item, str):
                    continue
                # If the value is not a full path (i.e. does not have '/'), build the full path
                if '/' not in item:
                    item = self._build_minio_path(ft, field, item, record_id)
                processed_list.append(item)
            
            data[field_name] = processed_list
                
        return data

    async def upload_attachment(
        self,
        record_id: str,
        field_name: str,
        file_bytes: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> FormRecordResponse:
        """Upload a file to MinIO and store the canonical path in record.data[field_name]."""
        record = await self.db.get(FormRecord, record_id)
        if not record:
            raise ValueError(f"Record {record_id} not found")
        if record.status != "Draft":
            raise ValueError("Attachments can only be uploaded for Draft records")

        ft = await self.db.get(FormType, record.form_type_id)
        if not ft:
            raise ValueError(f"FormType {record.form_type_id} not found")

        attach_field = self._get_attach_field(ft, field_name)
        if attach_field is None:
            raise ValueError(
                f"Field '{field_name}' is not an Attach field in form type '{ft.form_name}'"
            )

        object_name = self._build_minio_path(ft, attach_field, filename, record_id=record_id)

        success = storage_service.upload_file(
            file_data=file_bytes,
            object_name=object_name,
            content_type=content_type,
        )
        if not success:
            raise RuntimeError(f"Failed to upload file to MinIO at path: {object_name}")

        logger.info(f"Uploaded attachment for record {record_id}, field '{field_name}' -> {object_name}")

        # Persist the full path in the record
        data = dict(record.data) if record.data else {}
        
        # We append to list of attachments to support multiple file uploads
        existing_val = data.get(field_name)
        if isinstance(existing_val, list):
            new_list = list(existing_val)
            if object_name not in new_list:
                new_list.append(object_name)
            data[field_name] = new_list
        elif isinstance(existing_val, str) and existing_val:
            # For backwards compatibility with old records storing a single string path
            if existing_val.strip().startswith('[') and existing_val.strip().endswith(']'):
                try:
                    import json
                    parsed = json.loads(existing_val)
                    if isinstance(parsed, list):
                        new_list = list(parsed)
                        if object_name not in new_list:
                            new_list.append(object_name)
                        data[field_name] = new_list
                    else:
                        data[field_name] = [existing_val, object_name]
                except Exception:
                    data[field_name] = [existing_val, object_name]
            else:
                data[field_name] = [existing_val, object_name]
        else:
            data[field_name] = [object_name]
            
        record.data = data
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(record, "data")
        logger.debug(f"------Updated record data: {data}")
        await self.db.commit()
        await self.db.refresh(record)
        populated_data = await self._populate_child_records(record)
        return self._parse(record, populated_data)

    async def create(
        self,
        payload: FormRecordCreate,
        created_by: str = "system"
    ) -> FormRecordResponse:
        ft = await self.db.get(FormType, payload.form_type_id)
        if not ft:
            raise ValueError(f"FormType {payload.form_type_id} not found")

        docname = await self._next_docname(payload.form_type_id, ft.form_name)
        record_id = self._new_id()

        # Process attachments
        processed_data = self._process_attachments(ft, payload.data, record_id)

        project_stage_id = None
        if payload.stage_id:
            stage = await self.db.get(Stage, payload.stage_id)
            if stage:
                project_stage_id = StageService.resolve_project_stage_id(stage)

        record = FormRecord(
            record_id=record_id,
            form_type_id=payload.form_type_id,
            stage_id=payload.stage_id,
            project_stage_id=project_stage_id,
            docname=docname,
            status="Draft",
            assigned_role="worker",
            assigned_to=created_by,
            assigned_at=datetime.now(timezone.utc),
            data=processed_data, # Temporary, to be replaced by stripped data
            created_by=created_by,
            form_version=ft.version,
            schema_snapshot=ft.schema_reference,
            parent_record_id=payload.parent_record_id,
            parent_form_type_id=payload.parent_form_type_id,
            parent_field_name=payload.parent_field_name,
        )
        self.db.add(record)
        # Flush so `record.record_id` exists as a valid FK target before
        # _save_child_records below can point an existing linked record's
        # parent_record_id back at it.
        await self.db.flush()

        # Update parent record's data if present
        if payload.parent_record_id and payload.parent_field_name:
            parent_rec = await self.db.get(FormRecord, payload.parent_record_id)
            if parent_rec:
                parent_data = dict(parent_rec.data) if parent_rec.data else {}
                parent_data[payload.parent_field_name] = docname
                parent_rec.data = parent_data
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(parent_rec, "data")

        # Save child records recursively
        schema = ft.schema_reference or {}
        fields = schema.get("fields", []) if isinstance(schema, dict) else []
        
        cleaned_data = await self._save_child_records(
            parent_record=record,
            data=processed_data,
            schema_fields=fields,
            created_by=created_by,
            is_update=False
        )

        record.data = self._strip_child_records(cleaned_data, fields)
        await self.db.commit()
        await self.db.refresh(record)
        return self._parse(record, cleaned_data)

    async def get(self, record_id: str) -> Optional[FormRecordResponse]:
        record = await self.db.get(FormRecord, record_id)
        if not record:
            return None
        populated_data = await self._populate_child_records(record)
        return self._parse(record, populated_data)

    async def list_by_form_type(
        self,
        form_type_id: str,
        skip: int = 0,
        limit: int = 50,
        q_docname: Optional[str] = None,
        project_stage_id: Optional[str] = None,
    ) -> tuple[List[FormRecordResponse], int]:
        q = select(FormRecord).where(FormRecord.form_type_id == form_type_id)
        if q_docname:
            q = q.where(FormRecord.docname.ilike(f"%{q_docname}%"))
        if project_stage_id:
            q = q.where(FormRecord.project_stage_id == project_stage_id)
        total_res = await self.db.execute(
            select(func.count()).select_from(q.subquery())
        )
        total = total_res.scalar() or 0
        res = await self.db.execute(
            q.order_by(FormRecord.created_at.desc()).offset(skip).limit(limit)
        )
        records = res.scalars().all()
        
        items = []
        for r in records:
            populated_data = await self._populate_child_records(r)
            items.append(self._parse(r, populated_data))
            
        return items, total

    async def update(
        self, record_id: str, payload: FormRecordUpdate
    ) -> FormRecordResponse:
        record = await self.db.get(FormRecord, record_id)
        if not record:
            raise ValueError(f"Record {record_id} not found")
        if record.status != "Draft":
            raise ValueError("Only Draft records can be edited")

        ft = await self.db.get(FormType, record.form_type_id)
        processed_data = self._process_attachments(ft, payload.data, record_id)

        schema = ft.schema_reference or {}
        fields = schema.get("fields", []) if isinstance(schema, dict) else []
        
        cleaned_data = await self._save_child_records(
            parent_record=record,
            data=processed_data,
            schema_fields=fields,
            created_by=record.created_by or "system",
            is_update=True
        )

        record.data = self._strip_child_records(cleaned_data, fields)
        await self.db.commit()
        await self.db.refresh(record)
        return self._parse(record, cleaned_data)

    def _build_machine(self, workflow_data: dict, current_state: str) -> tuple[Machine, RecordContext]:
        if not workflow_data:
            # Fallback default workflow
            workflow_data = {
                "states": ["Draft", "Submitted", "Verified", "Completed", "Cancelled"],
                "initial": "Draft",
                "transitions": [
                    {"trigger": "submit", "source": "Draft", "dest": "Submitted"},
                    {"trigger": "verify", "source": "Submitted", "dest": "Verified"},
                    {"trigger": "amend", "source": "Verified", "dest": "Completed"},
                    {"trigger": "cancel", "source": ["Submitted", "Verified"], "dest": "Draft"}
                ]
            }

        states = workflow_data.get("states", [])
        transitions = workflow_data.get("transitions", [])
        
        # Filter out custom keys (actor_role, next_role) to prevent TypeError in transitions library
        clean_transitions = []
        valid_keys = {"trigger", "source", "dest", "conditions", "unless", "before", "after", "prepare"}
        for t in transitions:
            clean_t = {k: v for k, v in t.items() if k in valid_keys}
            clean_transitions.append(clean_t)
        
        ctx = RecordContext(current_state)
        machine = Machine(model=ctx, states=states, transitions=clean_transitions, initial=current_state)
        return machine, ctx

    def _find_transition(self, workflow_data: dict, trigger: str, current_state: str) -> Optional[dict]:
        """Find the matching transition definition from workflow_data."""
        if not workflow_data:
            return None
        for t in workflow_data.get("transitions", []):
            sources = t.get("source", [])
            if isinstance(sources, str):
                sources = [sources]
            if t.get("trigger") == trigger and current_state in sources:
                return t
        return None

    async def _can_execute_trigger(self, record: FormRecord, trigger: str, user_data: dict, workflow_data: dict) -> bool:
        user_roles = user_data.get("roles", [])
        if "superadmin" in user_roles:
            return True
            
        # 1. Check actor_role constraint from the transition definition
        if workflow_data:
            transition = self._find_transition(workflow_data, trigger, record.status)
            if transition:
                actor_role = transition.get("actor_role")
                if actor_role and actor_role not in user_roles:
                    return False
            
        # 2. Ownership check: if the record is assigned to a specific user,
        #    only that user (or superadmin) can act on it
        if record.assigned_to:
            if user_data.get("user_id") != record.assigned_to:
                return False
            
        # 3. Must satisfy explicit RBAC form type permissions (if mapped)
        t = trigger.lower()
        perm_type = None
        if t in ("submit",):
            perm_type = "can_submit"
        elif t in ("verify", "approve"):
            perm_type = "can_verify"
        elif t in ("cancel", "reject"):
            perm_type = "can_cancel"
        elif t in ("amend",):
            perm_type = "can_amend"
            
        if perm_type:
            from src.app.services.permission_service import PermissionService
            perm_service = PermissionService(self.db)
            has_perm = await perm_service.check_form_type_permission(
                user_data.get("user_id"), 
                record.form_type_id, 
                perm_type
            )
            if not has_perm:
                return False
                
        return True

    async def get_available_actions(self, record_id: str, user_data: dict) -> list[str]:
        record = await self.db.get(FormRecord, record_id)
        if not record: return []

        ft = await self.db.get(FormType, record.form_type_id)
        if ft.workflow_data is None:
            raise ValueError(f"FormType {record.form_type_id} has no workflow")
        
        # Get all potential machine triggers
        machine, ctx = self._build_machine(ft.workflow_data, record.status)
        triggers = machine.get_triggers(ctx.state)
        
        valid_triggers = []
        for t in triggers:
            if not t.startswith('to_'):
                if await self._can_execute_trigger(record, t, user_data, ft.workflow_data):
                    valid_triggers.append(t)
                    
        return valid_triggers

    async def process_transition(
        self,
        record_id: str,
        trigger: str,
        user_data: dict,
        remarks: str | None = None,
        rating: int | None = None,
        comment: str | None = None,
    ) -> FormRecordResponse:
        record = await self.db.get(FormRecord, record_id)
        if not record:
            raise ValueError(f"Record {record_id} not found")
        
        ft = await self.db.get(FormType, record.form_type_id)
        if ft.workflow_data is None:
            raise ValueError(f"FormType {record.form_type_id} has no workflow")
            
        # Security check: Does user have RBAC and workflow assignment rights for this trigger?
        if not await self._can_execute_trigger(record, trigger, user_data, ft.workflow_data):
             raise ValueError("You do not have permission to execute this transition")

        # A rating is mandatory on a quality judgement. Checked here, before any
        # state is touched, so a rejected transition cannot leave the record
        # half-moved.
        if trigger in RATEABLE_TRIGGERS and rating is None:
            raise ValueError(f"A rating is required to {trigger} this record")

        # The comment is NOT taken from the caller. The reviewer picks a star
        # value and the agreed wording for that value is looked up here, so the
        # text on a record is always one of the five approved ones — a crafted
        # API call cannot smuggle its own wording in. Anything the client sent
        # in `comment` is deliberately discarded.
        comment = None
        if rating is not None:
            comment = await RatingCommentPresetService(self.db).get_text(rating)
            if not comment:
                raise ValueError(
                    f"No comment text is configured for a rating of {rating}. "
                    f"Please configure the rating comment presets."
                )
        
        old_state = record.status
             
        machine, ctx = self._build_machine(ft.workflow_data, old_state)
        
        valid_triggers = machine.get_triggers(ctx.state)
        if trigger not in valid_triggers:
             raise ValueError(f"Invalid transition '{trigger}' from state '{ctx.state}'")
             
        try:
             getattr(ctx, trigger)()
        except Exception as e:
             raise ValueError(f"Transition failed: {e}")
             
        new_state = ctx.state
        record.status = new_state
        
        # ── Assignment chain: resolve next owner from workflow_assignments ──
        transition_def = self._find_transition(ft.workflow_data, trigger, old_state)
        next_role = transition_def.get("next_role") if transition_def else None

        if next_role:
            # Look up the user assigned to next_role for this stage+form_type
            assignment_svc = WorkflowAssignmentService(self.db)
            next_user_id = await assignment_svc.get_assigned_user(
                stage_id=record.stage_id,
                form_type_id=record.form_type_id,
                role=next_role,
            )
            if not next_user_id:
                raise ValueError(
                    f"No workflow assignment found for role '{next_role}' "
                    f"in stage '{record.stage_id}', form type '{record.form_type_id}'. "
                    f"Please configure assignments before processing transitions."
                )
            record.assigned_role = next_role
            record.assigned_to = next_user_id
            record.assigned_at = datetime.now(timezone.utc)
        else:
            # Terminal state — clear assignment fields
            record.assigned_role = None
            record.assigned_to = None
            record.assigned_at = None
             
        if trigger == "submit" and not record.submitted_by:
             record.submitted_by = user_data.get("user_id")
             record.submitted_at = datetime.now(timezone.utc)
        
        action = FormAction(
            record_id=record.record_id,
            action_type=trigger,
            from_state=old_state,
            to_state=new_state,
            performed_by=user_data.get("user_id"),
            remarks=remarks,
            rating=rating,
            comment=comment,
        )

        self.db.add(action)

        # The action row above is the history ("rated 2 at submit"); this is
        # the record's current score, which lists and averages read. Both are
        # written in the one commit below so they can never drift apart.
        if rating is not None:
            existing_rating = await self.db.get(FormRecordRating, record.record_id)
            if existing_rating is None:
                existing_rating = FormRecordRating(record_id=record.record_id)
                self.db.add(existing_rating)
            existing_rating.rating = rating
            existing_rating.comment = comment
            existing_rating.remark = remarks
            existing_rating.rated_by = user_data.get("user_id")
            existing_rating.rated_at = datetime.now(timezone.utc)
             
        await self.db.commit()
        await self.db.refresh(record)
        populated_data = await self._populate_child_records(record)
        return self._parse(record, populated_data)

    async def delete(self, record_id: str) -> None:
        record = await self.db.get(FormRecord, record_id)
        if not record:
            raise ValueError(f"Record {record_id} not found")
        if record.status != "Draft":
            raise ValueError("Only Draft records can be deleted")

        # Recursively delete all child records
        result = await self.db.execute(
            select(FormRecord).where(FormRecord.parent_record_id == record.record_id)
        )
        children = result.scalars().all()
        for child in children:
            await self.delete(child.record_id)

        # FormType lookup
        form_type = await self.db.get(FormType, record.form_type_id)
        if not form_type:
            raise ValueError(f"FormType {record.form_type_id} not found where it should be")

        # Minio delete folder
        record_path = f"{form_type.form_type_id}/{record.record_id}"
        try:
            storage_service.delete_file(record_path)
        except Exception as e:
            logger.warning(f"Failed to delete storage path {record_path}: {e}")
            
        await self.db.delete(record)
        await self.db.commit()
