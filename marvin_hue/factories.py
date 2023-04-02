from enum import Enum
from marvin_hue.setups import *


class LightConfigEnum(Enum):
    SETUP_BRIGHTNESS_COLORS = (SetupBrightnessColors, 'Ambiente com foco em brilho e cores')
    SETUP_CONCENTRATION = (SetupConcentration, 'Ambiente que estimula a concentração')
    SETUP_FUTURISTIC = (SetupFuturistic, 'Ambiente futurista e envolvente')
    SETUP_RELAXING = (SetupRelaxing, 'Ambiente relaxante e tranquilo')
    SETUP_STUDY = (SetupStudy, 'Ambiente propício para estudo')
    SETUP_ENTERTAINMENT = (SetupEntertainment, 'Ambiente para entretenimento e diversão')
    SOFT_WHITE_CONCENTRATION = (SoftWhiteConcentration, 'Concentração com luz suave e branca')
    COOL_BLUE_ENERGY = (CoolBlueEnergy, 'Energia e foco com luz azul fria')
    COZY_WARM_ORANGE = (CozyWarmOrange, 'Ambiente aconchegante com luz laranja quente')
    GREEN_TEAL_CALM = (GreenTealCalm, 'Ambiente calmo com tons de verde e azul')
    PURPLE_HOME = (PurpleHome, 'Ambiente relaxante com luz roxa.')
    PURPLE_RELAXATION = (
        PurpleRelaxation,
        """
        Ambiente relaxante com luz roxa com menor intensidade e com uma mistura de cores
        mais suaves para criar um ambiente mais relaxante e menos intenso.
        """
    )
    MULTI_COLOR_FOCUS = (MultiColorFocus, 'Foco e concentração com várias cores')
    VIBRANT_YELLOW_ENERGY = (VibrantYellowEnergy, 'Energia vibrante com luz amarela')
    PINK_DREAM = (PinkDream, 'Ambiente dos sonhos com luz rosa')
    OCEAN_BLUE_CALM = (OceanBlueCalm, 'Ambiente calmo com luz azul oceânica')
    RED_HOT_PASSION = (RedHotPassion, 'Ambiente apaixonado com luz vermelha')
    BRIGHT_DAYLIGHT = (BrightDaylight, 'Ambiente iluminado com luz natural')
    PASTEL_RAINBOW = (PastelRainbow, 'Ambiente colorido com tons pastéis')
    SOFT_GRADIENT_MIX = (SoftGradientMix, 'Ambiente suave com gradientes misturados')
    WARM_GLOW = (WarmGlow, 'Ambiente aconchegante com luz quente')
    COOL_GRADIENT_MIX = (CoolGradientMix, 'Ambiente fresco com gradientes misturados')
    MORNING_EYE_SOOTHING = (MorningEyeSoothing, 'Ambiente matinal suave para os olhos')
    DAWN_RELAXATION = (DawnRelaxation, 'Ambiente relaxante ao amanhecer')
    MORNING_MIST = (MorningMist, 'Ambiente matinal com névoa suave')
    FOCUSED_MORNING = (FocusedMorning, 'Ambiente matinal concentrado')
    AFTERNOON_DELIGHT = (AfternoonDelight, 'Ambiente alegre e energético durante a tarde.')
    VIDEO_LESSON_SOFT_LIGHT = (VideoLessonSoftLight, 'Ambiente com luz suave e uniforme, minimizando sombras.')
    VIDEO_LESSON_FOCUSED_LIGHT = (
        VideoLessonFocusedLight,
        'Ambiente com maior contraste e uma iluminação mais focada.'
    )
    VIDEO_LESSON_MATRIX_THEME = (
        VideoLessonMatrixTheme,
        'Ambiente com tons de verde, em referência ao icônico código de caracteres verdes '
        'que desce pela tela no filme "The Matrix".'
    )
    VIDEO_LESSON_MATRIX_THEME_BOLD = (
        VideoLessonMatrixThemeBold,
        'Ambiente com cores contrastantes, vermelho e azul, respectivamente, '
        'para dar um efeito ousado, baseado no tema "The Matrix".'
    )
    VIDEO_LESSON_PYTHON_LOGO_THEME = (
        VideoLessonPythonLogoTheme,
        'Ambiente com cores que fazem parte do logotipo do Python.'
    )
    CYBERPUNK_NIGHT = (
        CyberpunkNight,
        """
        Ambiente inspirado no gênero cyberpunk, com cores vibrantes e contrastantes que lembram a 
        estética de cidades futuristas e densas. As cores principais são roxo intenso, ciano e laranja, 
        criando um ambiente ousado e envolvente, perfeito para noites criativas e imersivas.        
        """
    )
    GALACTIC_ADVENTURE = (
        GalacticAdventure,
        """
        Ambiente inspirado no espaço e na exploração galáctica, este tema usa tons de azul, amarelo e verde, 
        criando uma atmosfera que lembra as estrelas, planetas e nebulosas. 
        O ambiente é futurista e convidativo, evocando uma sensação de descoberta e aventura, 
        ótimo para relaxar e sonhar acordado à noite.
        """
    )
    ELECTRIC_DREAMS = (
        ElectricDreams,
        """
        Ambiente com uma mistura ousada de cores vivas e energéticas, como rosa, ciano e amarelo. 
        Ele cria uma atmosfera futurista, quase psicodélica, que estimula a criatividade e a imaginação. 
        É perfeito para trabalhar em projetos criativos ou simplesmente desfrutar de um ambiente inovador 
        e intrigante à noite.
        """
    )
    FUTURISTIC_LASER_SHOW = (
        FuturisticLaserShow,
        """
        Ambiente futurista com um show de laser impressionante. Com cores brilhantes e ousadas, 
        este tema cria uma atmosfera emocionante e energética, perfeita para festas ou eventos especiais.
        """
    )
    CHEERFUL_PINK_PARTY = (
        CheerfulPinkParty,
        """
        Ambiente alegre com uma mistura de tons de rosa, criando uma atmosfera festiva e animada. 
        Este tema é perfeito para comemorações, encontros sociais ou simplesmente para adicionar 
        um toque de cor e alegria ao seu dia.
        """
    )
    TRANQUIL_ROSE_GARDEN = (
        TranquilRoseGarden,
        """
        Ambiente tranquilo e relaxante, inspirado em um jardim de rosas. Com tons suaves e acolhedores de rosa, 
        este tema cria uma atmosfera serena e calmante, ideal para relaxar, meditar ou desfrutar de um momento de paz.
        """
    )
    GOLDEN_SUNSET = (
        GoldenSunset,
        """
        Ambiente inspirado no pôr do sol dourado, com tons quentes e dourados que criam uma atmosfera 
        relaxante e aconchegante.
        """
    )
    TROPICAL_SUNSET = (
        TropicalSunset,
        """
        Ambiente inspirado em um pôr do sol tropical, com uma mistura de cores quentes e vibrantes que evocam 
        a sensação de estar na praia durante o crepúsculo.
        """
    )
    DESERT_SUNSET = (
        DesertSunset,
        """
        Ambiente inspirado em um pôr do sol no deserto, com tons quentes e terrosos que lembram as paisagens 
        desérticas e as dunas de areia.
        """
    )

    def __init__(self, light_config_class, description):
        self.light_config_class = light_config_class
        self.description = description

    def get_instance(self):
        return self.light_config_class()
