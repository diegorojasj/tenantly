import { defineMessages } from './define';

// Calendar — the day's timeline per resource.
export default defineMessages(
  {
    title: 'Calendar',
    lede: { one: '{n} {bookings} on {count} resource.', other: '{n} {bookings} on {count} resources.' },
    ledeZone: { one: '{n} {bookings} on {count} resource · {zone} time.', other: '{n} {bookings} on {count} resources · {zone} time.' },
    pickLocation: 'Pick a {location} to open its timeline.',
    previousDay: 'Previous day',
    nextDay: 'Next day',
    today: 'Today',
    newBooking: 'New {booking}',
    outOfService: 'Out of service',
    siteStats: '{bookings} · {pct}% {staff} time booked',
  },
  {
    title: 'Calendario',
    lede: { one: '{n} {bookings} en {count} recurso.', other: '{n} {bookings} en {count} recursos.' },
    ledeZone: { one: '{n} {bookings} en {count} recurso · hora de {zone}.', other: '{n} {bookings} en {count} recursos · hora de {zone}.' },
    pickLocation: 'Elige {location} para abrir su línea de tiempo.',
    previousDay: 'Día anterior',
    nextDay: 'Día siguiente',
    today: 'Hoy',
    newBooking: 'Agregar {booking}',
    outOfService: 'Fuera de servicio',
    siteStats: '{bookings} · {pct}% del tiempo de {staff} reservado',
  },
);
