import { defineMessages } from './define';

export default defineMessages(
  {
    meterCustomers: 'Customers served',
    meterPayments: 'Payments processed',
    serviceBilling: 'Billing',
    unitCustomers: 'customers',
    unitPayments: 'payments',

    headTitle: 'Billing · Tenantly',
    title: 'Plan & usage',
    eyebrow: '{plan} plan',
    lede: 'Priced on what you use, not on seats: the customers you serve and the payments you take each month. A busy month moves up a tier on its own, so nothing stops at a limit. Usage resets on the 1st.',

    statPlan: 'Billed this month',
    footPrice: '{price} a month',
    footMovedUp: 'moved up from {plan}: usage passed its limits',
    statNextInvoice: 'Next invoice',
    footEstimated: 'estimated · {date}',
    statCollected: 'Collected this month',
    footCollected: 'from your customers, in your currency',

    outgrown: 'This month passed the Enterprise limits. Talk to Tenantly about a Custom plan with the price and limits that fit your business.',

    usageTitle: 'Usage this month',
    meterUsage: '{used} of {limit} {unit} · {service}',
    meterUnlimited: '{used} {unit} · no limit · {service}',
    meterPerDay: '{label} per day',

    plansTitle: 'Plans',
    plansAside: 'Prices a month, in {currency}',
    plansFoot: 'Each tier doubles the usage of the one before it. Need more than Enterprise, or terms of your own? A Custom plan is agreed with Tenantly for your business.',
    colPlan: 'Plan',
    colPrice: 'Price',
    colCustomers: 'Customers a month',
    colPayments: 'Payments a month',
    negotiated: 'Negotiated',
    agreed: 'As agreed',
    noLimit: 'No limit',
    current: 'current',
    thisMonth: 'this month',
  },
  {
    meterCustomers: 'Clientes atendidos',
    meterPayments: 'Pagos procesados',
    serviceBilling: 'Facturación',
    unitCustomers: 'clientes',
    unitPayments: 'pagos',

    headTitle: 'Facturación · Tenantly',
    title: 'Plan y uso',
    eyebrow: 'Plan {plan}',
    lede: 'Se cobra por lo que usas, no por puestos: los clientes que atiendes y los pagos que recibes cada mes. Un mes con más actividad sube de nivel solo, así que nada se detiene en un límite. El uso se reinicia el día 1.',

    statPlan: 'Facturado este mes',
    footPrice: '{price} al mes',
    footMovedUp: 'subió desde {plan}: el uso pasó sus límites',
    statNextInvoice: 'Próxima factura',
    footEstimated: 'estimado · {date}',
    statCollected: 'Cobrado este mes',
    footCollected: 'de tus clientes, en tu moneda',

    outgrown: 'Este mes superó los límites de Enterprise. Habla con Tenantly sobre un plan Custom con el precio y los límites que se ajusten a tu negocio.',

    usageTitle: 'Uso de este mes',
    meterUsage: '{used} de {limit} {unit} · {service}',
    meterUnlimited: '{used} {unit} · sin límite · {service}',
    meterPerDay: '{label} por día',

    plansTitle: 'Planes',
    plansAside: 'Precios al mes, en {currency}',
    plansFoot: 'Cada nivel duplica el uso del anterior. ¿Necesitas más que Enterprise o condiciones propias? Un plan Custom se acuerda con Tenantly para tu negocio.',
    colPlan: 'Plan',
    colPrice: 'Precio',
    colCustomers: 'Clientes al mes',
    colPayments: 'Pagos al mes',
    negotiated: 'A negociar',
    agreed: 'Según lo acordado',
    noLimit: 'Sin límite',
    current: 'actual',
    thisMonth: 'este mes',
  },
);
