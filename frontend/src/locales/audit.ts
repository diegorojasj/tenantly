import { defineMessages } from './define';

export default defineMessages(
  {
    headTitle: 'Audit trail · Tenantly',
    title: 'Audit trail',
    eyebrow: 'Tamper-evident ledger',
    lede: 'A permanent record of every change: who did it, when, and where. Entries can’t be edited.',
    chainVerified: 'Chain verified',
    chainBroken: 'Chain broken',
    chainSummary: { one: '{count} entry · head', other: '{count} entries · head' },

    categoriesLabel: 'Categories',
    cat_access: 'access',
    cat_config: 'config',
    cat_billing: 'billing',
    cat_integration: 'integration',
    cat_security: 'security',
    searchPlaceholder: 'Actor, action, target, IP…',
    exportCsv: 'Export CSV',
    empty: 'No events match these filters.',
    hashTitle: 'prev {prev} → {hash}',
  },
  {
    headTitle: 'Registro de auditoría · Tenantly',
    title: 'Registro de auditoría',
    eyebrow: 'Registro a prueba de manipulaciones',
    lede: 'Un registro permanente de cada cambio: quién lo hizo, cuándo y dónde. Las entradas no se pueden editar.',
    chainVerified: 'Cadena verificada',
    chainBroken: 'Cadena rota',
    chainSummary: { one: '{count} entrada · cabeza', other: '{count} entradas · cabeza' },

    categoriesLabel: 'Categorías',
    cat_access: 'acceso',
    cat_config: 'configuración',
    cat_billing: 'facturación',
    cat_integration: 'integración',
    cat_security: 'seguridad',
    searchPlaceholder: 'Autor, acción, objetivo, IP…',
    exportCsv: 'Exportar CSV',
    empty: 'Ningún evento coincide con estos filtros.',
    hashTitle: 'ant. {prev} → {hash}',
  },
);
