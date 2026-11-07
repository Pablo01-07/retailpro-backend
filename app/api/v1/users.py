import math
import secrets
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.database import get_db
from app.core.security import get_password_hash
from app.core.dependencies import get_current_admin
from app.core.audit import create_audit_log, get_client_ip
from app.models.usuario import Usuario
from app.schemas.users import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    RoleOption
)

router = APIRouter(prefix="/usuarios", tags=["Administración de Usuarios"])

SYSTEM_ROLES = [
    RoleOption(
        code="administrador",
        name="Administrador de Sistemas",
        description="Acceso total a la plataforma, gestión de usuarios, auditoría, modelos y procesos."
    ),
    RoleOption(
        code="analista",
        name="Analista de Inventarios",
        description="Carga y calidad de datos, generación de pronósticos, recomendaciones y reportes."
    ),
    RoleOption(
        code="jefe_logistica",
        name="Jefe de Logística",
        description="Visualización de dashboard, monitoreo de nivel de servicio, centro de alertas y reportes."
    )
]


@router.get("/roles", response_model=List[RoleOption])
def get_roles(
    current_admin: Usuario = Depends(get_current_admin)
):
    """Obtiene el listado de roles del sistema para desplegables en formularios."""
    return SYSTEM_ROLES


@router.get("", response_model=UserListResponse)
def list_users(
    page: int = Query(1, ge=1, description="Número de página"),
    size: int = Query(10, ge=1, le=100, description="Registros por página"),
    rol: Optional[str] = Query(None, description="Filtrar por rol"),
    estado: Optional[bool] = Query(None, description="Filtrar por estado activo/inactivo"),
    search: Optional[str] = Query(None, description="Búsqueda por nombre o correo"),
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Lista usuarios con filtros por rol, estado y paginación (Mockup 22)."""
    query = db.query(Usuario)

    if rol:
        query = query.filter(Usuario.rol == rol)
    if estado is not None:
        query = query.filter(Usuario.estado == estado)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                Usuario.nombre_completo.ilike(search_filter),
                Usuario.correo.ilike(search_filter)
            )
        )

    total = query.count()
    pages = math.ceil(total / size) if total > 0 else 1
    items = query.order_by(Usuario.id_usuario.asc()).offset((page - 1) * size).limit(size).all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in items],
        total=total,
        page=page,
        size=size,
        pages=pages
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Crea un nuevo usuario en el sistema (Mockup 23). Solo administradores."""
    existing_user = db.query(Usuario).filter(Usuario.correo == user_in.correo).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario registrado con el correo {user_in.correo}"
        )

    valid_roles = [r.code for r in SYSTEM_ROLES]
    if user_in.rol not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rol no válido. Roles permitidos: {', '.join(valid_roles)}"
        )

    raw_password = user_in.password if user_in.password else f"RetailPro_{secrets.token_hex(4)}!"
    hashed_password = get_password_hash(raw_password)

    new_user = Usuario(
        nombre_completo=user_in.nombre_completo,
        correo=user_in.correo,
        clave_hash=hashed_password,
        rol=user_in.rol,
        estado=user_in.estado
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    client_ip = get_client_ip(request)
    create_audit_log(
        db=db,
        accion="crear_usuario",
        modulo_afectado="usuarios",
        user=current_admin,
        detalle={
            "id_usuario_creado": new_user.id_usuario,
            "correo": new_user.correo,
            "rol": new_user.rol,
            "ip": client_ip
        }
    )

    return UserResponse.model_validate(new_user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Obtiene el detalle de un usuario por su ID."""
    user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return UserResponse.model_validate(user)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_in: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Actualiza la información de un usuario (Mockup 23). Solo administradores."""
    user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    if user_in.correo and user_in.correo != user.correo:
        existing = db.query(Usuario).filter(Usuario.correo == user_in.correo).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El correo ya se encuentra en uso")
        user.correo = user_in.correo

    if user_in.nombre_completo is not None:
        user.nombre_completo = user_in.nombre_completo
    if user_in.rol is not None:
        valid_roles = [r.code for r in SYSTEM_ROLES]
        if user_in.rol not in valid_roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rol inválido")
        user.rol = user_in.rol
    if user_in.estado is not None:
        user.estado = user_in.estado
    if user_in.password:
        user.clave_hash = get_password_hash(user_in.password)

    db.commit()
    db.refresh(user)

    client_ip = get_client_ip(request)
    create_audit_log(
        db=db,
        accion="actualizar_usuario",
        modulo_afectado="usuarios",
        user=current_admin,
        detalle={"id_usuario_modificado": user.id_usuario, "correo": user.correo, "ip": client_ip}
    )

    return UserResponse.model_validate(user)


@router.delete("/{user_id}", response_model=UserResponse)
def deactivate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Desactiva lógicamente una cuenta de usuario."""
    if user_id == current_admin.id_usuario:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puede desactivar su propia cuenta de administrador")

    user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    user.estado = False
    db.commit()
    db.refresh(user)

    client_ip = get_client_ip(request)
    create_audit_log(
        db=db,
        accion="desactivar_usuario",
        modulo_afectado="usuarios",
        user=current_admin,
        detalle={"id_usuario_desactivado": user.id_usuario, "correo": user.correo, "ip": client_ip}
    )

    return UserResponse.model_validate(user)
