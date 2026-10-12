import { defineMessages } from './define';

// The workspace shell: navigation rail, scope lens and top bar.
export default defineMessages(
  {
    // Navigation
    navToday: 'Today',
    navCalendar: 'Calendar',
    navCatalog: 'Catalog',
    navResources: 'Resources',
    navPayments: 'Payments',
    navInsights: 'Insights',
    navAccess: 'Team & roles',
    navConfig: 'Policies',
    navSettings: 'Business settings',
    navAudit: 'Audit trail',
    navBilling: 'Plan & usage',
    groupSetup: 'Set up',
    groupMoney: 'Money & insight',
    groupAdmin: 'Admin',
    navLabel: 'Workspace',

    // Rail
    allWorkspaces: 'Tenantly — all workspaces',
    scope: 'Scope',
    isolationTitle: "This workspace's isolation boundary",
    tenantKey: 'Tenant key',
    residency: 'Residency',
    identity: 'Identity',

    // Top bar
    toggleNav: 'Toggle navigation',
    currentScope: 'Current scope',
    widenTo: 'Widen to {name}',
    jumpTo: 'Jump to…',
    signOut: 'Sign out',

    // Tenantly plan standing
    billingPastDue: 'Your Tenantly invoice is overdue. Nothing is blocked yet.',
    billingLimited: 'Your Tenantly invoice is unpaid: new customers are on hold. Existing customers can still book.',
    billingRestricted: 'Your Tenantly invoice is unpaid: new customers and new bookings are on hold. Check-ins and payments still work.',
    billingCanceled: 'Your Tenantly plan has ended: this workspace is read-only.',
    accountRestricted: 'Tenantly has restricted your account: you can look around, but not change anything. Contact Tenantly support.',
    billingOpen: 'Plan & usage →',
  },
  {
    navToday: 'Hoy',
    navCalendar: 'Calendario',
    navCatalog: 'Catálogo',
    navResources: 'Recursos',
    navPayments: 'Pagos',
    navInsights: 'Análisis',
    navAccess: 'Equipo y roles',
    navConfig: 'Políticas',
    navSettings: 'Ajustes del negocio',
    navAudit: 'Registro de auditoría',
    navBilling: 'Plan y uso',
    groupSetup: 'Configuración',
    groupMoney: 'Dinero y análisis',
    groupAdmin: 'Administración',
    navLabel: 'Espacio de trabajo',

    allWorkspaces: 'Tenantly — todos los espacios de trabajo',
    scope: 'Ámbito',
    isolationTitle: 'El límite de aislamiento de este espacio de trabajo',
    tenantKey: 'Clave del inquilino',
    residency: 'Residencia de datos',
    identity: 'Identidad',

    toggleNav: 'Mostrar u ocultar la navegación',
    currentScope: 'Ámbito actual',
    widenTo: 'Ampliar a {name}',
    jumpTo: 'Ir a…',
    signOut: 'Cerrar sesión',

    billingPastDue: 'Tu factura de Tenantly está vencida. Aún no hay nada bloqueado.',
    billingLimited: 'Tu factura de Tenantly está sin pagar: los clientes nuevos están en pausa. Los clientes actuales pueden seguir reservando.',
    billingRestricted: 'Tu factura de Tenantly está sin pagar: los clientes y las reservas nuevas están en pausa. Los check-ins y los cobros siguen funcionando.',
    billingCanceled: 'Tu plan de Tenantly terminó: este espacio de trabajo es de solo lectura.',
    accountRestricted: 'Tenantly restringió tu cuenta: puedes consultar, pero no cambiar nada. Contacta con el soporte de Tenantly.',
    billingOpen: 'Plan y uso →',
  },
);
