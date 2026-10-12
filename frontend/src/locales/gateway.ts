import { defineMessages } from './define';

// The gateway (sign in, pick a workspace) and the 404 page. Nobody signs up here:
// Tenantly creates owners' accounts, and owners create their team's.
export default defineMessages(
  {
    // 404
    notFoundTitle: 'Nothing at this address',
    notFoundLede: "The page may have moved, or it lives in a workspace you can't see.",
    backToWorkspaces: 'Back to workspaces',

    // Account
    headTitle: 'Sign in',
    foot: 'One platform for any business that sells time, capacity or access, each in its own isolated workspace.',
    welcomeBack: 'Welcome back',
    signIn: 'Sign in',
    email: 'Email',
    password: 'Password',
    inviteHint: 'Sign in with the email address the invite was sent to and you will join that business.',
    noAccountHint:
      "No account? Your business's owner creates accounts for their team; to open a business on Tenantly, contact Tenantly.",

    // Workspaces
    greeting: 'Hi {name}',
    invited: "You've been invited to a business.",
    acceptInvite: 'Accept invite',
    noWorkspaceTitle: 'No workspace yet',
    noWorkspaceLede:
      "You don't belong to a business yet. Ask its owner to add this email address to their team, or contact Tenantly to open a business.",
    pickWorkspace: 'Pick a workspace',
    signOut: 'Sign out',
  },
  {
    notFoundTitle: 'No hay nada en esta dirección',
    notFoundLede: 'Puede que la página se haya movido o que esté en un espacio de trabajo que no puedes ver.',
    backToWorkspaces: 'Volver a los espacios de trabajo',

    headTitle: 'Iniciar sesión',
    foot: 'Una plataforma para cualquier negocio que vende tiempo, capacidad o acceso, cada uno en su propio espacio de trabajo aislado.',
    welcomeBack: 'Hola de nuevo',
    signIn: 'Inicia sesión',
    email: 'Correo electrónico',
    password: 'Contraseña',
    inviteHint: 'Inicia sesión con el correo electrónico al que se envió la invitación y te unirás a ese negocio.',
    noAccountHint:
      '¿No tienes cuenta? El propietario de tu negocio crea las cuentas de su equipo; para abrir un negocio en Tenantly, contacta con Tenantly.',

    greeting: 'Hola, {name}',
    invited: 'Te invitaron a un negocio.',
    acceptInvite: 'Aceptar invitación',
    noWorkspaceTitle: 'Aún no tienes espacio de trabajo',
    noWorkspaceLede:
      'Todavía no perteneces a ningún negocio. Pide a su propietario que agregue este correo electrónico a su equipo, o contacta con Tenantly para abrir un negocio.',
    pickWorkspace: 'Elige un espacio de trabajo',
    signOut: 'Cerrar sesión',
  },
);
