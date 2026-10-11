"""Spanish wording for the seeded templates, and for the roles businesses copied from them.

Each overlay has the template's wire shape with only the words (common/i18n.py):
list items name the item they word by `key` (or `id` for roles). Choice `options`
are stored values, so they are never translated.
"""

from django.db import migrations

# Shared wording: every template carries the same tree level and starting roles (0009),
# the same waiver (0007), and the legacy templates the same generic presets (0006).
LEVELS = [{"key": "area", "label": "Zona", "plural": "Zonas"}]

ROLES = [
    {"id": "owner", "label": "Propietario", "summary": "Control total del negocio, incluida la facturación."},
    {
        "id": "admin",
        "label": "Administrador",
        "summary": "Gestiona la operación diaria; no puede cambiar el plan de Tenantly.",
    },
    {
        "id": "regional_manager",
        "label": "Gerente de zona",
        "summary": "Gestiona reservas, catálogo y políticas de una zona.",
    },
    {
        "id": "location_manager",
        "label": "Jefe de recepción",
        "summary": "Gestiona la recepción de una sola sede: reservas, llegadas y pagos.",
    },
    {"id": "analyst", "label": "Analista", "summary": "Acceso de solo lectura a reservas, cifras y configuración."},
    {
        "id": "auditor",
        "label": "Auditor",
        "summary": "Acceso de solo lectura al registro de auditoría y la facturación.",
    },
]

WAIVER = {"key": "waiver", "label": "Descargo de responsabilidad"}

PRESETS = {
    "appointment": {
        "key": "appointment",
        "label": "Cita",
        "plural": "Citas",
        "intro": "Un cliente, un miembro del equipo, una duración fija.",
    },
    "class": {
        "key": "class",
        "label": "Clase",
        "plural": "Clases",
        "intro": "Varios clientes comparten una sesión, hasta un cupo.",
    },
    "rental": {
        "key": "rental",
        "label": "Alquiler",
        "plural": "Alquileres",
        "intro": "Un cliente usa una unidad durante un período de tiempo.",
    },
    "visit": {
        "key": "visit",
        "label": "Visita",
        "plural": "Visitas",
        "intro": "Un miembro del equipo va al domicilio del cliente.",
    },
    "plan": {
        "key": "plan",
        "label": "Plan",
        "plural": "Planes",
        "intro": "Acceso recurrente o un paquete de créditos, no un horario.",
    },
}

ES: dict[str, dict] = {
    "general": {
        "label": "Negocio",
        "description": "Cualquier negocio que vende tiempo, capacidad o acceso.",
        "presets": [
            {
                "key": "appointment",
                "label": "Cita",
                "plural": "Citas",
                "intro": "Un cliente a la vez con un miembro del equipo: un corte de pelo, una consulta, una clase "
                "particular.",
            },
            {
                "key": "class",
                "label": "Clase o grupo",
                "plural": "Clases y grupos",
                "intro": "Varios clientes comparten una sesión, hasta un límite: una clase, un tour, un taller.",
            },
            {
                "key": "rental",
                "label": "Alquiler",
                "plural": "Alquileres",
                "intro": "Un cliente usa una sala o un artículo por un tiempo: por hora, día, noche o mes.",
            },
            {
                "key": "visit",
                "label": "Visita",
                "plural": "Visitas",
                "intro": "Un miembro del equipo va al domicilio del cliente: reparaciones, limpieza, cuidados.",
            },
            {
                "key": "plan",
                "label": "Plan o membresía",
                "plural": "Planes y membresías",
                "intro": "Acceso recurrente o un paquete de créditos; no se reserva en el calendario.",
            },
        ],
        "resourceTypes": [
            {
                "key": "staff",
                "label": "Miembro del equipo",
                "plural": "Equipo",
                "roleLabel": "Especialidad",
            },
            {
                "key": "asset",
                "label": "Sala o artículo",
                "plural": "Salas y artículos",
                "roleLabel": "Tipo",
            },
        ],
        "terms": {
            "customer": "Cliente",
            "customers": "Clientes",
            "booking": "Reserva",
            "bookings": "Reservas",
            "staff": "Miembro del equipo",
            "staffPlural": "Equipo",
            "asset": "Sala o artículo",
            "assets": "Salas y artículos",
            "location": "Sede",
            "locations": "Sedes",
        },
        "status": {
            "requested": "Solicitada",
            "confirmed": "Confirmada",
            "checked_in": "Presente",
            "completed": "Completada",
            "no_show": "No asistió",
            "cancelled": "Cancelada",
        },
        "accountTypes": [
            {"key": "business", "label": "Empresa", "plural": "Empresas"},
            {"key": "household", "label": "Hogar", "plural": "Hogares"},
        ],
        "documents": [WAIVER],
        "levels": LEVELS,
        "roles": ROLES,
    },
    "fitness": {
        "label": "Fitness",
        "description": "Gimnasios, estudios y clubes: clases, entrenamiento personal y membresías.",
        "presets": [PRESETS["class"], PRESETS["appointment"], PRESETS["plan"]],
        "resourceTypes": [
            {
                "key": "staff",
                "label": "Entrenador",
                "plural": "Entrenadores",
                "roleLabel": "Especialidad",
            },
            {
                "key": "asset",
                "label": "Sala",
                "plural": "Salas",
                "roleLabel": "Tipo",
                "attributes": [{"key": "capacity", "label": "Capacidad"}],
            },
        ],
        "terms": {
            "customer": "Socio",
            "customers": "Socios",
            "booking": "Reserva",
            "bookings": "Reservas",
            "staff": "Entrenador",
            "staffPlural": "Entrenadores",
            "asset": "Sala",
            "assets": "Salas",
            "location": "Sede",
            "locations": "Sedes",
        },
        "status": {
            "requested": "En espera",
            "confirmed": "Reservada",
            "checked_in": "Presente",
            "completed": "Asistió",
            "no_show": "No asistió",
            "cancelled": "Cancelada",
        },
        "fields": {
            "customer": [
                {"key": "goal", "label": "Objetivo"},
                {"key": "injuries", "label": "Lesiones"},
                {"key": "emergency", "label": "Contacto de emergencia"},
            ]
        },
        "accountTypes": [{"key": "household", "label": "Familia", "plural": "Familias"}],
        "documents": [WAIVER],
        "levels": LEVELS,
        "roles": ROLES,
    },
    "rentals": {
        "label": "Alquileres y tours",
        "description": "Kayaks, bicicletas, tablas, canchas o salas por hora, además de tours guiados.",
        "presets": [PRESETS["rental"], PRESETS["class"]],
        "resourceTypes": [
            {
                "key": "staff",
                "label": "Guía",
                "plural": "Guías",
                "roleLabel": "Especialidad",
            },
            {
                "key": "asset",
                "label": "Unidad",
                "plural": "Flota",
                "roleLabel": "Tipo",
                "attributes": [{"key": "seats", "label": "Asientos"}],
            },
        ],
        "terms": {
            "customer": "Cliente",
            "customers": "Clientes",
            "booking": "Reserva",
            "bookings": "Reservas",
            "staff": "Guía",
            "staffPlural": "Guías",
            "asset": "Unidad",
            "assets": "Flota",
            "location": "Muelle",
            "locations": "Muelles",
        },
        "status": {
            "requested": "Solicitada",
            "confirmed": "Reservada",
            "checked_in": "En uso",
            "completed": "Devuelta",
            "no_show": "No se presentó",
            "cancelled": "Cancelada",
        },
        "fields": {
            "customer": [
                {"key": "id", "label": "Identificación verificada"},
                {"key": "experience", "label": "Experiencia"},
                {"key": "emergency", "label": "Contacto de emergencia"},
            ]
        },
        "accountTypes": [{"key": "business", "label": "Grupo", "plural": "Grupos"}],
        "documents": [WAIVER],
        "levels": LEVELS,
        "roles": ROLES,
    },
    "field": {
        "label": "Servicios a domicilio",
        "description": "Equipos que van al cliente: limpieza, mantenimiento, reparaciones, planes de servicio.",
        "presets": [PRESETS["visit"], PRESETS["plan"]],
        "resourceTypes": [
            {
                "key": "staff",
                "label": "Técnico",
                "plural": "Técnicos",
                "roleLabel": "Especialidad",
            },
            {
                "key": "asset",
                "label": "Camioneta",
                "plural": "Camionetas",
                "roleLabel": "Tipo",
                "attributes": [{"key": "plate", "label": "Placa"}],
            },
        ],
        "terms": {
            "customer": "Cuenta",
            "customers": "Cuentas",
            "booking": "Visita",
            "bookings": "Visitas",
            "staff": "Técnico",
            "staffPlural": "Técnicos",
            "asset": "Camioneta",
            "assets": "Camionetas",
            "location": "Ruta",
            "locations": "Rutas",
        },
        "status": {
            "requested": "Solicitada",
            "confirmed": "Programada",
            "checked_in": "En sitio",
            "completed": "Completada",
            "no_show": "Sin acceso",
            "cancelled": "Cancelada",
        },
        "fields": {
            "customer": [
                {"key": "address", "label": "Dirección"},
                {"key": "system", "label": "Sistema"},
                {"key": "access", "label": "Notas de acceso"},
            ]
        },
        "accountTypes": [
            {
                "key": "business",
                "label": "Empresa",
                "plural": "Empresas",
                "fields": [{"key": "taxId", "label": "ID fiscal"}],
            },
            {"key": "household", "label": "Hogar", "plural": "Hogares"},
        ],
        "subjectTypes": [
            {
                "key": "property",
                "label": "Inmueble",
                "plural": "Inmuebles",
                "fields": [
                    {"key": "address", "label": "Dirección"},
                    {"key": "system", "label": "Sistema"},
                    {"key": "serviced", "label": "Último servicio"},
                ],
            }
        ],
        "documents": [{"key": "gas_cert", "label": "Certificado de seguridad de gas"}],
        "levels": LEVELS,
        "roles": ROLES,
    },
}


def _roles(overlay):
    return {r["id"]: r for r in overlay.get("roles", [])}


def forward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    Role = apps.get_model("identity", "Role")
    Tenant = apps.get_model("identity", "Tenant")
    for template in Template.objects.filter(id__in=ES):
        template.translations = {**template.translations, "es": ES[template.id]}
        template.save(update_fields=["translations"])
        # Roles still worded as the template words them get its Spanish too.
        base = {r["id"]: r for r in template.roles}
        spanish = _roles(ES[template.id])
        tenants = Tenant.objects.filter(template_id=template.id).values_list("id", flat=True)
        for role in Role.objects.filter(tenant_id__in=list(tenants), builtin=True):
            source, words = base.get(role.key), spanish.get(role.key)
            if not source or not words:
                continue
            es = {
                field: words[field]
                for field in ("label", "summary")
                if field in words and getattr(role, field) == source.get(field, "")
            }
            if es:
                role.translations = {**role.translations, "es": es}
                role.save(update_fields=["translations"])


def backward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    Role = apps.get_model("identity", "Role")
    for template in Template.objects.filter(id__in=ES):
        template.translations = {k: v for k, v in template.translations.items() if k != "es"}
        template.save(update_fields=["translations"])
    for role in Role.objects.exclude(translations={}):
        role.translations = {k: v for k, v in role.translations.items() if k != "es"}
        role.save(update_fields=["translations"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0011_translations")]

    operations = [migrations.RunPython(forward, backward)]
