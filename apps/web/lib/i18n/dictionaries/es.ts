import type { Messages } from "./en";
import { FREE_FIRST_REEL } from "@/lib/offer";

/**
 * Spanish message catalog. Typed against `Messages`, so it must mirror the
 * English key structure exactly.
 */
export const es: Messages = {
  common: {
    menivor: "Menivor",
    signIn: "Iniciar sesión",
    myReels: "Mis reels",
    wallet: "Cartera",
    tryAgain: "Reintentar",
    loading: "Cargando…",
  },
  languageSwitcher: {
    label: "Idioma",
  },
  nav: {
    howItWorks: "Cómo funciona",
    captions: "Subtítulos",
    pricing: "Precios",
    freeTools: "Herramientas gratis",
    showcase: "Galería",
    styles: "Estilos",
    editor: "Editor",
    joinWaitlist: "Unirse a la lista de espera",
    signIn: "Iniciar sesión",
    makeReelFree: "Crea un reel gratis",
    startFree: "Crear mi primer video",
    requestAccess: "Solicitar acceso anticipado",
    goToReels: "Ir a mis reels",
    openMenu: "Abrir menú",
    closeMenu: "Cerrar menú",
    homeAria: "Inicio de Menivor",
  },
  footer: {
    howItWorks: "Cómo funciona",
    captions: "Subtítulos",
    pricing: "Precios",
    platforms: "Por plataforma",
    make: "Qué crear",
    tools: "Herramientas",
    guides: "Guías",
    features: "Funciones",
    providers: "Proveedores",
    turkish: "Türkçe",
    waitlist: "Lista de espera",
    signIn: "Iniciar sesión",
    terms: "Términos",
    privacy: "Privacidad",
    refunds: "Reembolsos",
    contact: "Contacto",
    tagline: "grabación de pantalla → reel terminado",
  },
  landing: {
    heroKicker: "grabación de pantalla → reel terminado",
    heroTitle: "Convierte tu grabación de pantalla en un video UGC con IA.",
    heroBody:
      "Menivor toma una captura de pantalla en bruto y realiza todo el montaje: escribe un guion con gancho, lo narra con una voz de IA natural, incrusta subtítulos karaoke palabra por palabra y renderiza un video 9:16 listo para TikTok, Reels y Shorts.",
    heroWaitlistNote:
      "Menivor está en un piloto cerrado mientras la capacidad de renderizado entra en marcha. Deja tu correo y te abriremos un lugar.",
    heroMakeReelFree: "Crea un reel gratis",
    heroSeePricing: "Ver precios",
    heroFreeNote: FREE_FIRST_REEL
      ? "Tu primer reel es gratis, sin tarjeta. Luego una verificación de tarjeta de $1 desbloquea 3 más."
      : "Regístrate gratis. Una verificación de tarjeta de $1 desbloquea 3 reels gratis.",
    howKicker: "el flujo",
    howTitle: "Entra una grabación. Sale un reel terminado.",
    step1Label: "graba",
    step1Title: "Empieza con cualquier grabación de pantalla",
    step1Body:
      "Captura tu producto, demo o flujo de trabajo — sirve un archivo existente, o usa el grabador de escritorio de Menivor con captura de ventana y pantalla completa, micrófono más audio del sistema y una pista de webcam imagen en imagen.",
    step2Label: "genera",
    step2Title: "El flujo realiza el montaje",
    step2Body:
      "Menivor escribe un guion con gancho, lo narra con una voz de IA natural sobre tu metraje e incrusta subtítulos karaoke palabra por palabra — en turco o inglés.",
    step3Label: "publica",
    step3Title: "Renderiza en 9:16 y publica",
    step3Body:
      "El video vertical terminado sale listo para TikTok, Reels y Shorts — descárgalo o entrégalo a los conectores de publicación cuando tus cuentas estén vinculadas.",
    ctaKicker: "acceso anticipado",
    ctaTitle: "Sé el primero cuando se abra la generación.",
    ctaWaitlistBody:
      "Menivor está en un piloto cerrado mientras la capacidad del proveedor entra en marcha. Únete a la lista de espera y recibirás un solo correo cuando se abra tu lugar — nada más.",
    ctaLiveBody: "Convierte tu próxima grabación de pantalla en un reel que valga la pena publicar.",
    ctaCreateFirst: "Crea tu primer reel",
    ctaComparePlans: "Comparar planes",
    publicKicker: "abierto ahora",
    publicTitle: "Haz tu primer reel hoy.",
    publicBody: "Menivor está abierto a todos en el plan gratuito. Crea una cuenta gratis, desbloquea 3 reels gratis con una verificación de tarjeta de $1 y empieza con los formatos disponibles hoy.",
    startFree: "Crear mi primer video",
    signupNote:
      "Regístrate con un clic con Google o Apple. Una verificación de tarjeta de 1 $ desbloquea 3 reels gratis, y ese 1 $ se convierte en 1 reel más.",
    openNowLabel: "Disponible ahora en el plan gratuito:",
    updatesTitle: "Recibe novedades del lanzamiento",
    updatesBody: "Un correo cuando se abran los paquetes de pago y la publicación en redes sociales.",
    updatesSubmit: "Recibir novedades",
    updatesSuccess: "Gracias. Te escribiremos cuando se abran los paquetes de pago y la publicación.",
  },
  pricing: {
    kicker: "precios",
    title: "Un plan mensual o un pack único, con precio por reel.",
    intro:
      "Crea reels cada mes con un plan, o compra un pack de créditos una vez y úsalo cuando lo necesites. Los créditos de los packs nunca caducan y un render fallido nunca cuesta un crédito.",
    howHeading: "Cómo funcionan los créditos de Menivor",
    howPara1:
      "Un crédito paga un reel terminado. Menivor reserva el crédito cuando comienza el renderizado y lo cobra después de que el video tiene éxito. Un render fallido devuelve la reserva a tu saldo. Los créditos comprados no caducan, así que puedes renderizar alrededor de lanzamientos y campañas sin mantener activa una suscripción mensual.",
    howPara2:
      "Las cuentas nuevas desbloquean tres reels gratis con una verificación de tarjeta de $1, y ese $1 se convierte en un cuarto reel. Los paquetes de créditos cubren el guion, la locución, los subtítulos karaoke y la composición final 9:16 en un solo render. El selector de paquetes muestra la cantidad de créditos y el precio de pago antes de comprar. Los equipos que necesitan más volumen pueden contactarnos para una asignación mayor.",
    howPara3:
      "Estima un paquete a partir del número de reels terminados de tu campaña y luego guarda un pequeño margen para ganchos o diseños alternativos. Un borrador que decides renderizar de nuevo usa otro crédito porque crea un nuevo video terminado. Revisa el guion y la grabación fuente antes de iniciar un render para no gastar créditos en revisiones evitables.",
    volumeQuestion: "¿Preguntas sobre precios por volumen? Escribe a",
    waitlistCtaLabel: "Se abre con el acceso anticipado",
    waitlistKicker: "acceso anticipado",
    waitlistBody:
      "El pago se abre cuando lo hace tu cuenta. Únete a la lista de espera y te escribiremos una vez — tus reels gratis te esperan al otro lado.",
  },
  create: {
    navFromTemplate: "Desde una plantilla",
    navGuidedWizard: "Asistente guiado",
    navMyReels: "Mis reels",
    navWallet: "Cartera",
    title: "Crear un video",
    subtitle:
      "Convierte una nota de voz en un reel 9:16 con subtítulos, o genera un video con IA a partir de un texto o una sola imagen. Tus primeros créditos son gratis, sin cuenta.",
    tabNarrationLabel: "Reel de narración",
    tabNarrationHint: "Tu voz + subtítulos — gratis",
    tabAiVideoLabel: "Video con IA",
    tabAiVideoHint: "Texto o imagen → video — 3 créditos",
    tablistLabel: "Modo de creación",
  },
  newReel: {
    title: "Crear un nuevo reel",
    subtitle:
      "Sube una grabación de pantalla y le escribiremos el guion, le pondremos voz e incrustaremos subtítulos karaoke — luego renderizamos un video 9:16 listo para publicar.",
  },
  library: {
    title: "Biblioteca de reels",
    subtitleFallback: "Cada reel que has generado, con estado de render en vivo.",
    subtitleCount: "{count} reels · sesión iniciada como {email}",
    subtitleCountOne: "{count} reel · sesión iniciada como {email}",
    calendar: "Calendario",
    scheduled: "Programados",
    newReel: "Nuevo reel",
    credits: "créditos",
    creditsTitle: "Créditos disponibles",
    loadError: "No se pudieron cargar tus reels.",
    loadErrorTitle: "No se pudieron cargar tus reels",
    emptyTitle: "Aún no hay reels",
    emptyBody: "Genera tu primer reel para verlo aquí.",
    noMatchTitle: "Ningún reel coincide con tus filtros",
    noMatchBody: "Prueba otro estado o borra tu búsqueda.",
    showAll: "Mostrar todos los reels",
  },
  discover: {
    title: "Descubrir",
    subtitle:
      "Sonidos en tendencia, hashtags emergentes, formatos virales y plantillas recomendadas — clasificados por oportunidad para que construyas antes de que la ola alcance su pico.",
    refresh: "Actualizar",
    risingNow: "En alza ahora",
    risingNowDesc:
      "Tendencias con mayor oportunidad en todos los tipos — puntuadas por velocidad y saturación.",
    noTrends: "Sin tendencias en vivo aún. Vuelve pronto.",
    buildNow: "crea ya",
    sounds: "Sonidos en tendencia",
    soundsDesc: "Sonidos con velocidad creciente y baja saturación — úsalos antes de que la ola alcance el pico.",
    hashtags: "Hashtags emergentes",
    hashtagsDesc: "Hashtags ganando tracción — úsalos antes de que se saturen.",
    viralFormats: "Formatos virales",
    viralFormatsDesc:
      "Géneros de plantillas de toma probados que el pipeline puede convertir en un reel listo.",
    explorerCta: "¿Quieres clasificar tus propios datos de tendencia?",
    explorerCtaLink: "Abre el explorador de tendencias",
    explorerCtaTail: "para pegar cualquier serie de recuentos y puntuarla.",
    backToDiscover: "Volver a Descubrir",
    opportunityScore: "Oportunidad",
    phaseLabel: "Fase",
    saturationLabel: "Saturación",
    buildNowLabel: "Crea ya",
    noDataSoon: "Sin datos aún — vuelve pronto.",
    soundsPageTitle: "Sonidos en Tendencia",
    soundsPageSubtitle:
      "Sonidos con velocidad creciente y baja saturación. Úsalos en tu reel antes de que la ola alcance el pico.",
    soundsEmpty: "Sin sonidos en tendencia ahora. Vuelve pronto.",
    hashtagsPageTitle: "Hashtags Emergentes",
    hashtagsPageSubtitle:
      "Hashtags ganando impulso ahora — úsalos en tu contenido antes de que saturen el feed.",
    hashtagsEmpty: "Sin hashtags en tendencia ahora. Vuelve pronto.",
    formatsPageTitle: "Formatos Emergentes",
    formatsPageSubtitle:
      "Patrones de formato viral y plantillas de toma ganando tracción — la señal más cercana a creadores en auge que expone la API.",
    formatsSignalNote:
      "Esta página muestra tendencias de tipo formato del feed en vivo y plantillas de toma viral. No hay un endpoint de analíticas por creador; la señal de formato es el mejor proxy disponible.",
    formatsEmpty: "Sin formatos emergentes ahora. Vuelve pronto.",
    trendingTemplates: "Plantillas en tendencia",
    trendingTemplatesDesc:
      "Géneros de plantillas de toma viral listos para convertir en tu próximo reel.",
  },
  showcase: {
    title: "Vitrina",
    subtitle:
      "Explora plantillas de toma virales y tus reels completados.",
    templatesHeading: "Galería de plantillas",
    templatesDesc:
      "Formatos de género probados que el pipeline puede convertir en un reel listo.",
    myReelsHeading: "Tus reels completados",
    myReelsDesc:
      "Reels que has renderizado — inicia sesión para ver los tuyos.",
    signInPrompt: "Inicia sesión para ver tus reels completados aquí.",
    noTemplates: "No hay plantillas disponibles.",
    noReels:
      "Aún no hay reels completados. Crea tu primer reel para verlo aquí.",
    useTemplate: "Usar plantilla",
    previewReel: "Ver reel",
    slots: "segmentos",
  },
  analyticsDeep: {
    views: {
      title: "Desglose de vistas",
      subtitle:
        "Recuentos de trabajos por diseño de composición e idioma en la ventana seleccionada.",
      byLayout: "Por diseño",
      byLanguage: "Por idioma",
      noData: "Sin datos de vistas para esta ventana.",
    },
    retention: {
      title: "Retención y embudo",
      subtitle:
        "Tasa de finalización, trabajos fallidos, percentiles de tiempo de renderizado y progresión del embudo.",
      created: "Creados",
      completed: "Completados",
      failed: "Fallidos",
      published: "Publicados",
      completionRate: "Tasa de finalización",
      failRate: "Tasa de fallo",
      renderTime: "Tiempo de render",
      p50: "p50",
      p90: "p90",
      avg: "prom",
      samples: "muestras medidas",
      noData: "Sin datos de embudo para esta ventana.",
    },
    hooks: {
      title: "Hooks más usados",
      subtitle:
        "Tus líneas de apertura y plantillas más usadas — datos de todos los tiempos del servicio de analíticas.",
      hooksHeading: "Hooks",
      templatesHeading: "Plantillas",
      noData: "Sin datos aún. Renderiza reels para ver qué aperturas usas más.",
    },
  },
  apiDocs: {
    title: "Referencia de API",
    subtitle:
      "Endpoints públicos de Menivor — reels, plantillas, tendencias y analíticas.",
    authNote:
      "Autenticación: envía tu clave API como encabezado de solicitud x-api-key.",
    requestLabel: "Solicitud de ejemplo",
    paramsLabel: "Parámetros",
    responseLabel: "Forma de respuesta",
    required: "obligatorio",
    optional: "opcional",
    backToOverview: "Resumen",
  },
  editor: {
    title: "Editor de reels",
    backAria: "Volver al trabajo de origen",
    loadingTitle: "Cargando reel de origen",
    jobLabel: "Trabajo {id}",
    loadErrorTitle: "No se pudo cargar el reel de origen",
    renderFailedTitle: "Este render falló",
    renderNotReadyTitle: "El render no está listo",
    pauseAria: "Pausar la vista previa",
    playAria: "Reproducir el rango seleccionado",
    cutRangeHeading: "Rango de corte",
    cutRangeHelp:
      "Fija los puntos de entrada y salida, luego previsualiza solo esa sección. El render original no cambia.",
    inPoint: "Punto de entrada",
    outPoint: "Punto de salida",
    selected: "Seleccionado",
    source: "Origen",
    previewCut: "Previsualizar corte",
    resetRange: "Restablecer rango",
    copyCutValues: "Copiar valores del corte",
    copied: "Copiado",
    exportSelection: "Exportar selección",
    queuingExport: "Poniendo la exportación en cola",
    exportFailedFallback: "La exportación falló en el worker de render.",
    downloadExportedCut: "Descargar corte exportado",
    downloadSource: "Descargar origen",
    timeline: "Línea de tiempo",
    seekAria: "Navegar por la línea de tiempo",
    advancedHeading: "Avanzado — línea de tiempo multiclip",
    loadingDuration:
      "Cargando la duración de origen antes de habilitar las ediciones de la línea de tiempo…",
    noSourceTitle: "Elige un reel terminado",
    noSourceDetail:
      "Elige abajo un reel terminado para cargar su render en el editor.",
    openJobs: "Abrir reel",
    openLibrary: "Abrir biblioteca de reels",
    openExportedReel: "Abrir reel exportado",
  },
  studioCatalog: {
    brollTitle: "Biblioteca de B-roll",
    brollSubtitle:
      "Tus clips de B-roll generados por IA — filtra por estado, úsalos en un reel o descárgalos.",
    brollGenerate: "Generar B-roll",
    captionsTitle: "Subtítulos",
    captionsSubtitle:
      "Zonas seguras de subtítulos por plataforma y herramientas — del renderizador que usa el pipeline.",
    captionStyles: "Estilos de subtítulos",
    voicesTitle: "Voces",
    voicesSubtitle:
      "Voces narradoras y proveedores de lipsync — elige una voz y ve qué motor la renderizará.",
    myVoices: "Mis voces",
    avatarsTitle: "Avatares",
    avatarsSubtitle:
      "Avatares del proveedor y tus personajes con identidad bloqueada — elige un presentador o bloquea un personaje.",
    characters: "Personajes",
    clipsTitle: "Clips",
    clipsSubtitle:
      "Trabajos de recorte largo a corto — ver clips producidos y promocionar cualquier clip a borrador de reel.",
    newReel: "Nuevo reel",
    refresh: "Actualizar",
    promoteToReel: "Promocionar a reel",
    openDraft: "Abrir borrador",
    safezoneTitle: "Zonas seguras por plataforma",
    safezoneSubtitle:
      "Posición de subtítulos que el renderizador graba para cada superficie de plataforma.",
    captionTools: "Herramientas de subtítulos",
    voicesLipsync: "Proveedores de lipsync",
    voicesNarrator: "Voces narradoras",
    avatarsProvider: "Avatares",
    avatarsCharacters: "Personajes",
    clippingJobs: "Trabajos de recorte",
    clipPromoted: "Clip promocionado a borrador de reel",
    noVoices: "No hay voces disponibles. Revisa tu configuración de API.",
    noAvatars: "No hay avatares disponibles ahora. Inténtalo más tarde.",
    noCharacters: "Aún no hay personajes guardados. Crea uno para bloquear una identidad entre tomas.",
    noClips: "Aún no hay trabajos de recorte. Inicia uno desde una grabación larga o una URL.",
    noSafezones: "No se devolvieron datos de zona segura.",
    createCharacter: "Crear personaje",
    manageCharacters: "Gestionar personajes",
    createClippingJob: "Crear trabajo de recorte",
    useVoice: "Usar voz",
    useAvatar: "Usar avatar",
    useInFilm: "Usar en película",
  },
  shareToX: {
    button: "Compartir en X",
    buttonAria: "Compartir en X. Abre el compositor en una pestaña nueva.",
    downloadAndShareAria:
      "Descarga el MP4 y compártelo en X. Abre el compositor en una pestaña nueva.",
    hint: "X no puede adjuntar el video desde aquí. Descarga el MP4 y añádelo en el compositor.",
  },
};
