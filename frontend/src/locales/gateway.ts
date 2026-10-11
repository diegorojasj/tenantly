import { defineMessages } from './define';

// The gateway (sign in / up, pick or create a workspace) and the 404 page.
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
    getStarted: 'Get started',
    signIn: 'Sign in',
    createYourAccount: 'Create your account',
    yourName: 'Your name',
    email: 'Email',
    password: 'Password',
    passwordHint: 'At least 8 characters.',
    createAccount: 'Create account',
    newHere: 'New to Tenantly?',
    haveAccount: 'Already have an account?',
    createAnAccount: 'Create an account',
    inviteHint: 'Use the email address the invite was sent to and you will join that business.',
    invitedHint: 'Invited by a business? Open the invite link you were given.',

    // Workspaces
    greeting: 'Hi {name}',
    invited: "You've been invited to a business.",
    acceptInvite: 'Accept invite',
    setUpTitle: 'Set up your business',
    setUpLede:
      "You don't belong to a workspace yet. Create one for your business — or ask your manager to invite this email address.",
    pickWorkspace: 'Pick a workspace',
    createAnother: 'Create another business',
    signOut: 'Sign out',

    // Create a business
    businessName: 'Business name',
    businessNamePlaceholder: 'e.g. Northside Studio',
    industry: 'What you do (optional)',
    industryPlaceholder: 'e.g. Yoga classes, bike hire, home repairs',
    firstLocation: 'Name your first location',
    firstLocationPlaceholder: 'e.g. Downtown',
    moreLocationsLater: 'You can add more locations later.',
    createBusiness: 'Create business',
    cancel: 'Cancel',
  },
  {
    notFoundTitle: 'No hay nada en esta dirección',
    notFoundLede: 'Puede que la página se haya movido o que esté en un espacio de trabajo que no puedes ver.',
    backToWorkspaces: 'Volver a los espacios de trabajo',

    headTitle: 'Iniciar sesión',
    foot: 'Una plataforma para cualquier negocio que vende tiempo, capacidad o acceso, cada uno en su propio espacio de trabajo aislado.',
    welcomeBack: 'Hola de nuevo',
    getStarted: 'Empieza',
    signIn: 'Inicia sesión',
    createYourAccount: 'Crea tu cuenta',
    yourName: 'Tu nombre',
    email: 'Correo electrónico',
    password: 'Contraseña',
    passwordHint: 'Al menos 8 caracteres.',
    createAccount: 'Crear cuenta',
    newHere: '¿Nuevo en Tenantly?',
    haveAccount: '¿Ya tienes una cuenta?',
    createAnAccount: 'Crea una cuenta',
    inviteHint: 'Usa el correo electrónico al que se envió la invitación y te unirás a ese negocio.',
    invitedHint: '¿Te invitó un negocio? Abre el enlace de invitación que te dieron.',

    greeting: 'Hola, {name}',
    invited: 'Te invitaron a un negocio.',
    acceptInvite: 'Aceptar invitación',
    setUpTitle: 'Configura tu negocio',
    setUpLede:
      'Todavía no perteneces a ningún espacio de trabajo. Crea uno para tu negocio, o pide a tu gerente que invite a este correo electrónico.',
    pickWorkspace: 'Elige un espacio de trabajo',
    createAnother: 'Crear otro negocio',
    signOut: 'Cerrar sesión',

    businessName: 'Nombre del negocio',
    businessNamePlaceholder: 'p. ej., Estudio Norte',
    industry: 'A qué te dedicas (opcional)',
    industryPlaceholder: 'p. ej., clases de yoga, alquiler de bicicletas, reparaciones del hogar',
    firstLocation: 'Nombra tu primera sede',
    firstLocationPlaceholder: 'p. ej., Centro',
    moreLocationsLater: 'Puedes agregar más sedes después.',
    createBusiness: 'Crear negocio',
    cancel: 'Cancelar',
  },
);
