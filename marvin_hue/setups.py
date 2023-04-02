from marvin_hue.colors import Color


class LightSetting:
    def __init__(self, light_name, color: Color):
        self.light_name = light_name
        self.color = color


class LightConfig:
    def __init__(self, name, settings):
        self.name = name
        self.settings: list[LightSetting] = settings

    def __str__(self):
        return self.name


class SetupBrightnessColors(LightConfig):
    def __init__(self):
        super().__init__(
            "brightness_color",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 244, 229, 170)),
                LightSetting('Lâmpada 2', Color(255, 244, 229, 170)),
                LightSetting('Lâmpada 4', Color(255, 244, 229, 170)),
                LightSetting('Hue Iris', Color(255, 140, 80, 130)),
                LightSetting('Hue Play 1', Color(80, 180, 255, 100)),
                LightSetting('Hue Play 2', Color(80, 180, 255, 100)),
                LightSetting('Fita Led', Color(255, 215, 120, 80)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class SetupConcentration(LightConfig):
    def __init__(self):
        color = (255, 244, 229)
        super().__init__(
            "concentration",
            settings=[
                LightSetting('Lâmpada 1', Color(*color, 255)),
                LightSetting('Lâmpada 2', Color(*color, 255)),
                LightSetting('Lâmpada 4', Color(*color, 255)),
                LightSetting('Hue Iris', Color(*color, 130)),
                LightSetting('Hue Play 1', Color(*color, 100)),
                LightSetting('Hue Play 2', Color(*color, 100)),
                LightSetting('Fita Led', Color(*color, 40)),
                LightSetting('Led cima', Color(*color, 40)),
            ]
        )


class SetupFuturistic(LightConfig):
    def __init__(self):
        super().__init__(
            "futuristic",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 244, 229, 180)),
                LightSetting('Lâmpada 2', Color(255, 244, 229, 180)),
                LightSetting('Lâmpada 4', Color(255, 244, 229, 180)),
                LightSetting('Hue Iris', Color(255, 50, 255, 140)),
                LightSetting('Hue Play 1', Color(30, 255, 255, 110)),
                LightSetting('Hue Play 2', Color(30, 255, 255, 110)),
                LightSetting('Fita Led', Color(200, 255, 100, 90)),
                LightSetting('Led cima', Color(255, 244, 229, 50)),
            ]
        )


class SetupStudy(LightConfig):
    def __init__(self):
        super().__init__(
            "study",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 255, 240, 170)),
                LightSetting('Lâmpada 2', Color(255, 255, 240, 170)),
                LightSetting('Lâmpada 4', Color(255, 255, 240, 170)),
                LightSetting('Hue Iris', Color(150, 150, 255, 120)),
                LightSetting('Hue Play 1', Color(255, 255, 255, 100)),
                LightSetting('Hue Play 2', Color(255, 255, 255, 100)),
                LightSetting('Fita Led', Color(255, 200, 100, 80)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class SetupRelaxing(LightConfig):
    def __init__(self):
        super().__init__(
            "relaxing",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 200, 150, 150)),
                LightSetting('Lâmpada 2', Color(255, 200, 150, 150)),
                LightSetting('Lâmpada 4', Color(255, 200, 150, 150)),
                LightSetting('Hue Iris', Color(200, 100, 255, 120)),
                LightSetting('Hue Play 1', Color(100, 255, 200, 90)),
                LightSetting('Hue Play 2', Color(100, 255, 200, 90)),
                LightSetting('Fita Led', Color(255, 150, 100, 70)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class SetupEntertainment(LightConfig):
    def __init__(self):
        super().__init__(
            "entertainment",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 100, 100, 160)),
                LightSetting('Lâmpada 2', Color(100, 255, 100, 160)),
                LightSetting('Lâmpada 4', Color(100, 100, 255, 160)),
                LightSetting('Hue Iris', Color(255, 255, 100, 130)),
                LightSetting('Hue Play 1', Color(255, 100, 255, 100)),
                LightSetting('Hue Play 2', Color(100, 255, 255, 100)),
                LightSetting('Fita Led', Color(255, 150, 150, 80)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class SoftWhiteConcentration(LightConfig):
    def __init__(self):
        super().__init__(
            "soft_white_concentration",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 230, 220, 170)),
                LightSetting('Lâmpada 2', Color(255, 230, 220, 170)),
                LightSetting('Lâmpada 4', Color(255, 230, 220, 170)),
                LightSetting('Hue Iris', Color(150, 255, 200, 130)),
                LightSetting('Hue Play 1', Color(200, 255, 230, 100)),
                LightSetting('Hue Play 2', Color(200, 255, 230, 100)),
                LightSetting('Fita Led', Color(255, 200, 150, 50)),
                LightSetting('Led cima', Color(200, 255, 255, 40)),
            ]
        )


class CoolBlueEnergy(LightConfig):
    def __init__(self):
        super().__init__(
            "cool_blue_energy",
            settings=[
                LightSetting('Lâmpada 1', Color(220, 255, 230, 170)),
                LightSetting('Lâmpada 2', Color(220, 255, 230, 170)),
                LightSetting('Lâmpada 4', Color(220, 255, 230, 170)),
                LightSetting('Hue Iris', Color(255, 180, 100, 130)),
                LightSetting('Hue Play 1', Color(100, 200, 255, 100)),
                LightSetting('Hue Play 2', Color(100, 200, 255, 100)),
                LightSetting('Fita Led', Color(255, 150, 200, 80)),
                LightSetting('Led cima', Color(255, 200, 200, 40)),
            ]
        )


class CozyWarmOrange(LightConfig):
    def __init__(self):
        super().__init__(
            "cozy_warm_orange",
            settings=[
                LightSetting('Lâmpada 1', Color(240, 240, 255, 170)),
                LightSetting('Lâmpada 2', Color(240, 240, 255, 170)),
                LightSetting('Lâmpada 4', Color(240, 240, 255, 170)),
                LightSetting('Hue Iris', Color(200, 100, 255, 130)),
                LightSetting('Hue Play 1', Color(255, 255, 200, 100)),
                LightSetting('Hue Play 2', Color(255, 255, 200, 100)),
                LightSetting('Fita Led', Color(150, 255, 150, 80)),
                LightSetting('Led cima', Color(200, 200, 255, 40)),
            ]
        )


class GreenTealCalm(LightConfig):
    def __init__(self):
        super().__init__(
            "green_teal_calm",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 255, 230, 170)),
                LightSetting('Lâmpada 2', Color(255, 255, 230, 170)),
                LightSetting('Lâmpada 4', Color(255, 255, 230, 170)),
                LightSetting('Hue Iris', Color(255, 140, 180, 130)),
                LightSetting('Hue Play 1', Color(180, 140, 255, 100)),
                LightSetting('Hue Play 2', Color(180, 140, 255, 100)),
                LightSetting('Fita Led', Color(255, 220, 150, 80)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class PurpleHome(LightConfig):
    def __init__(self):
        super().__init__(
            "purple_home",
            settings=[
                LightSetting('Lâmpada 1', Color(170, 120, 255, 80)),
                LightSetting('Lâmpada 2', Color(170, 120, 255, 80)),
                LightSetting('Lâmpada 4', Color(170, 120, 255, 80)),
                LightSetting('Hue Iris', Color(200, 50, 255, 100)),
                LightSetting('Hue Play 1', Color(150, 50, 255, 100)),
                LightSetting('Hue Play 2', Color(150, 50, 255, 100)),
                LightSetting('Fita Led', Color(100, 0, 255, 70)),
                LightSetting('Led cima', Color(80, 0, 255, 40)),
            ]
        )


class PurpleRelaxation(LightConfig):
    def __init__(self):
        super().__init__(
            "purple_relaxation",
            settings=[
                LightSetting('Lâmpada 1', Color(200, 150, 255, 100)),
                LightSetting('Lâmpada 2', Color(200, 150, 255, 100)),
                LightSetting('Lâmpada 4', Color(200, 150, 255, 100)),
                LightSetting('Hue Iris', Color(120, 80, 180, 70)),
                LightSetting('Hue Play 1', Color(150, 100, 200, 80)),
                LightSetting('Hue Play 2', Color(150, 100, 200, 80)),
                LightSetting('Fita Led', Color(180, 130, 255, 60)),
                LightSetting('Led cima', Color(200, 150, 255, 40)),
            ]
        )


class MultiColorFocus(LightConfig):
    def __init__(self):
        super().__init__(
            "multi_color_focus",
            settings=[
                LightSetting('Lâmpada 1', Color(230, 255, 255, 170)),
                LightSetting('Lâmpada 2', Color(230, 255, 255, 170)),
                LightSetting('Lâmpada 4', Color(230, 255, 255, 170)),
                LightSetting('Hue Iris', Color(255, 200, 140, 130)),
                LightSetting('Hue Play 1', Color(140, 255, 200, 100)),
                LightSetting('Hue Play 2', Color(140, 255, 200, 100)),
                LightSetting('Fita Led', Color(150, 200, 255, 80)),
                LightSetting('Led cima', Color(255, 220, 255, 40)),
            ]
        )


class VibrantYellowEnergy(LightConfig):
    def __init__(self):
        super().__init__(
            "vibrant_yellow_energy",
            settings=[
                LightSetting('Lâmpada 1', Color(220, 240, 255, 170)),
                LightSetting('Lâmpada 2', Color(220, 240, 255, 170)),
                LightSetting('Lâmpada 4', Color(220, 240, 255, 170)),
                LightSetting('Hue Iris', Color(200, 255, 140, 130)),
                LightSetting('Hue Play 1', Color(140, 200, 255, 100)),
                LightSetting('Hue Play 2', Color(140, 200, 255, 100)),
                LightSetting('Fita Led', Color(255, 150, 220, 80)),
                LightSetting('Led cima', Color(255, 255, 220, 40)),
            ]
        )


class PinkDream(LightConfig):
    def __init__(self):
        super().__init__(
            "pink_dream",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 255, 240, 170)),
                LightSetting('Lâmpada 2', Color(255, 255, 240, 170)),
                LightSetting('Lâmpada 4', Color(255, 255, 240, 170)),
                LightSetting('Hue Iris', Color(140, 255, 140, 130)),
                LightSetting('Hue Play 1', Color(255, 140, 255, 100)),
                LightSetting('Hue Play 2', Color(255, 140, 255, 100)),
                LightSetting('Fita Led', Color(255, 200, 200, 80)),
                LightSetting('Led cima', Color(220, 255, 255, 40)),
            ]
        )


class OceanBlueCalm(LightConfig):
    def __init__(self):
        super().__init__(
            "ocean_blue_calm",
            settings=[
                LightSetting('Lâmpada 1', Color(200, 255, 240, 170)),
                LightSetting('Lâmpada 2', Color(200, 255, 240, 170)),
                LightSetting('Lâmpada 4', Color(200, 255, 240, 170)),
                LightSetting('Hue Iris', Color(255, 170, 140, 130)),
                LightSetting('Hue Play 1', Color(140, 255, 170, 100)),
                LightSetting('Hue Play 2', Color(140, 255, 170, 100)),
                LightSetting('Fita Led', Color(255, 255, 170, 80)),
                LightSetting('Led cima', Color(240, 240, 255, 40)),
            ]
        )


class RedHotPassion(LightConfig):
    def __init__(self):
        super().__init__(
            "red_hot_passion",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 240, 240, 170)),
                LightSetting('Lâmpada 2', Color(255, 240, 240, 170)),
                LightSetting('Lâmpada 4', Color(255, 240, 240, 170)),
                LightSetting('Hue Iris', Color(255, 200, 200, 130)),
                LightSetting('Hue Play 1', Color(200, 255, 200, 100)),
                LightSetting('Hue Play 2', Color(200, 255, 200, 100)),
                LightSetting('Fita Led', Color(200, 200, 255, 80)),
                LightSetting('Led cima', Color(255, 255, 240, 40)),
            ]
        )


class BrightDaylight(LightConfig):
    def __init__(self):
        super().__init__(
            "bright_daylight",
            settings=[
                LightSetting('Lâmpada 1', Color(240, 240, 255, 170)),
                LightSetting('Lâmpada 2', Color(240, 240, 255, 170)),
                LightSetting('Lâmpada 4', Color(240, 240, 255, 170)),
                LightSetting('Hue Iris', Color(200, 200, 255, 130)),
                LightSetting('Hue Play 1', Color(255, 200, 200, 100)),
                LightSetting('Hue Play 2', Color(255, 200, 200, 100)),
                LightSetting('Fita Led', Color(200, 255, 200, 80)),
                LightSetting('Led cima', Color(255, 240, 255, 40)),
            ]
        )


class PastelRainbow(LightConfig):
    def __init__(self):
        super().__init__(
            "pastel_rainbow",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 200, 220, 170)),
                LightSetting('Lâmpada 2', Color(255, 200, 220, 170)),
                LightSetting('Lâmpada 4', Color(255, 200, 220, 170)),
                LightSetting('Hue Iris', Color(200, 255, 240, 130)),
                LightSetting('Hue Play 1', Color(220, 200, 255, 100)),
                LightSetting('Hue Play 2', Color(220, 200, 255, 100)),
                LightSetting('Fita Led', Color(255, 220, 200, 80)),
                LightSetting('Led cima', Color(240, 255, 255, 40)),
            ]
        )


class SoftGradientMix(LightConfig):
    def __init__(self):
        super().__init__(
            "soft_gradient_mix",
            settings=[
                LightSetting('Lâmpada 1', Color(200, 220, 255, 170)),
                LightSetting('Lâmpada 2', Color(200, 220, 255, 170)),
                LightSetting('Lâmpada 4', Color(200, 220, 255, 170)),
                LightSetting('Hue Iris', Color(220, 255, 200, 130)),
                LightSetting('Hue Play 1', Color(255, 220, 220, 100)),
                LightSetting('Hue Play 2', Color(255, 220, 220, 100)),
                LightSetting('Fita Led', Color(220, 255, 220, 80)),
                LightSetting('Led cima', Color(255, 255, 240, 40)),
            ]
        )


class WarmGlow(LightConfig):
    def __init__(self):
        super().__init__(
            "warm_glow",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 230, 200, 170)),
                LightSetting('Lâmpada 2', Color(255, 230, 200, 170)),
                LightSetting('Lâmpada 4', Color(255, 230, 200, 170)),
                LightSetting('Hue Iris', Color(230, 255, 210, 130)),
                LightSetting('Hue Play 1', Color(210, 230, 255, 100)),
                LightSetting('Hue Play 2', Color(210, 230, 255, 100)),
                LightSetting('Fita Led', Color(255, 210, 230, 80)),
                LightSetting('Led cima', Color(230, 255, 255, 40)),
            ]
        )


class CoolGradientMix(LightConfig):
    def __init__(self):
        super().__init__(
            "cool_gradient_mix",
            settings=[
                LightSetting('Lâmpada 1', Color(210, 255, 230, 170)),
                LightSetting('Lâmpada 2', Color(210, 255, 230, 170)),
                LightSetting('Lâmpada 4', Color(210, 255, 230, 170)),
                LightSetting('Hue Iris', Color(230, 210, 255, 130)),
                LightSetting('Hue Play 1', Color(255, 230, 210, 100)),
                LightSetting('Hue Play 2', Color(255, 230, 210, 100)),
                LightSetting('Fita Led', Color(230, 255, 230, 80)),
                LightSetting('Led cima', Color(255, 230, 255, 40)),
            ]
        )


class MorningEyeSoothing(LightConfig):
    def __init__(self):
        super().__init__(
            "morning_eye_soothing",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 244, 229, 100)),
                LightSetting('Lâmpada 2', Color(255, 244, 229, 100)),
                LightSetting('Lâmpada 4', Color(255, 244, 229, 100)),
                LightSetting('Hue Iris', Color(255, 140, 80, 70)),
                LightSetting('Hue Play 1', Color(80, 180, 255, 50)),
                LightSetting('Hue Play 2', Color(80, 180, 255, 50)),
                LightSetting('Fita Led', Color(255, 215, 120, 40)),
                LightSetting('Led cima', Color(255, 244, 229, 20)),
            ]
        )


class DawnRelaxation(LightConfig):
    def __init__(self):
        super().__init__(
            "dawn_relaxation",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 235, 215, 100)),
                LightSetting('Lâmpada 2', Color(255, 235, 215, 100)),
                LightSetting('Lâmpada 4', Color(255, 235, 215, 100)),
                LightSetting('Hue Iris', Color(255, 160, 100, 70)),
                LightSetting('Hue Play 1', Color(100, 180, 200, 50)),
                LightSetting('Hue Play 2', Color(100, 180, 200, 50)),
                LightSetting('Fita Led', Color(255, 225, 150, 40)),
                LightSetting('Led cima', Color(255, 235, 215, 20)),
            ]
        )


class MorningMist(LightConfig):
    def __init__(self):
        super().__init__(
            "morning_mist",
            settings=[
                LightSetting('Lâmpada 1', Color(225, 225, 235, 100)),
                LightSetting('Lâmpada 2', Color(225, 225, 235, 100)),
                LightSetting('Lâmpada 4', Color(225, 225, 235, 100)),
                LightSetting('Hue Iris', Color(200, 200, 255, 70)),
                LightSetting('Hue Play 1', Color(180, 200, 225, 50)),
                LightSetting('Hue Play 2', Color(180, 200, 225, 50)),
                LightSetting('Fita Led', Color(215, 215, 255, 40)),
                LightSetting('Led cima', Color(225, 225, 235, 20)),
            ]
        )


class FocusedMorning(LightConfig):
    def __init__(self):
        super().__init__(
            "focused_morning",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 244, 229, 140)),
                LightSetting('Lâmpada 2', Color(255, 244, 229, 140)),
                LightSetting('Lâmpada 4', Color(255, 244, 229, 140)),
                LightSetting('Hue Iris', Color(255, 160, 100, 80)),
                LightSetting('Hue Play 1', Color(100, 200, 255, 60)),
                LightSetting('Hue Play 2', Color(100, 200, 255, 60)),
                LightSetting('Fita Led', Color(255, 215, 120, 50)),
                LightSetting('Led cima', Color(255, 244, 229, 30)),
            ]
        )


class AfternoonDelight(LightConfig):
    def __init__(self):
        super().__init__(
            "afternoon_delight",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 230, 200, 150)),
                LightSetting('Lâmpada 2', Color(255, 230, 200, 150)),
                LightSetting('Lâmpada 4', Color(255, 230, 200, 150)),
                LightSetting('Hue Iris', Color(255, 150, 100, 130)),
                LightSetting('Hue Play 1', Color(100, 255, 200, 100)),
                LightSetting('Hue Play 2', Color(100, 255, 200, 100)),
                LightSetting('Fita Led', Color(255, 215, 120, 80)),
                LightSetting('Led cima', Color(255, 230, 200, 50)),
            ]
        )


class VideoLessonSoftLight(LightConfig):
    def __init__(self):
        super().__init__(
            "video_lesson_soft_light",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 244, 229, 170)),
                LightSetting('Lâmpada 2', Color(255, 244, 229, 170)),
                LightSetting('Lâmpada 4', Color(255, 244, 229, 170)),
                LightSetting('Hue Iris', Color(255, 244, 229, 120)),
                LightSetting('Hue Play 1', Color(255, 244, 229, 100)),
                LightSetting('Hue Play 2', Color(255, 244, 229, 100)),
                LightSetting('Fita Led', Color(255, 244, 229, 60)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class VideoLessonFocusedLight(LightConfig):
    def __init__(self):
        super().__init__(
            "video_lesson_focused_light",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 244, 229, 200)),
                LightSetting('Lâmpada 2', Color(255, 244, 229, 200)),
                LightSetting('Lâmpada 4', Color(255, 244, 229, 200)),
                LightSetting('Hue Iris', Color(255, 200, 150, 120)),
                LightSetting('Hue Play 1', Color(255, 244, 229, 100)),
                LightSetting('Hue Play 2', Color(255, 244, 229, 100)),
                LightSetting('Fita Led', Color(255, 200, 150, 60)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class VideoLessonMatrixTheme(LightConfig):
    def __init__(self):
        super().__init__(
            "video_lesson_matrix_theme",
            settings=[
                LightSetting('Lâmpada 1', Color(30, 255, 30, 170)),
                LightSetting('Lâmpada 2', Color(30, 255, 30, 170)),
                LightSetting('Lâmpada 4', Color(30, 255, 30, 170)),
                LightSetting('Hue Iris', Color(30, 255, 30, 120)),
                LightSetting('Hue Play 1', Color(30, 255, 30, 100)),
                LightSetting('Hue Play 2', Color(30, 255, 30, 100)),
                LightSetting('Fita Led', Color(30, 255, 30, 60)),
                LightSetting('Led cima', Color(30, 255, 30, 40)),
            ]
        )


class VideoLessonMatrixThemeBold(LightConfig):
    def __init__(self):
        super().__init__(
            "video_lesson_matrix_theme_bold",
            settings=[
                LightSetting('Lâmpada 1', Color(30, 255, 30, 200)),
                LightSetting('Lâmpada 2', Color(30, 255, 30, 200)),
                LightSetting('Lâmpada 4', Color(30, 255, 30, 200)),
                LightSetting('Hue Iris', Color(30, 255, 30, 180)),
                LightSetting('Hue Play 1', Color(255, 20, 20, 100)),
                LightSetting('Hue Play 2', Color(20, 20, 255, 100)),
                LightSetting('Fita Led', Color(30, 255, 30, 120)),
                LightSetting('Led cima', Color(255, 255, 255, 60)),
            ]
        )


class VideoLessonPythonLogoTheme(LightConfig):
    def __init__(self):
        super().__init__(
            "video_lesson_python_logo_theme",
            settings=[
                LightSetting('Lâmpada 1', Color(2, 136, 209, 200)),
                LightSetting('Lâmpada 2', Color(2, 136, 209, 200)),
                LightSetting('Lâmpada 4', Color(2, 136, 209, 200)),
                LightSetting('Hue Iris', Color(252, 53, 76, 180)),
                LightSetting('Hue Play 1', Color(255, 215, 0, 100)),
                LightSetting('Hue Play 2', Color(2, 136, 209, 100)),
                LightSetting('Fita Led', Color(255, 215, 0, 120)),
                LightSetting('Led cima', Color(255, 255, 255, 60)),
            ]
        )


class CyberpunkNight(LightConfig):
    def __init__(self):
        super().__init__(
            "cyberpunk_night",
            settings=[
                LightSetting('Lâmpada 1', Color(153, 0, 255, 180)),
                LightSetting('Lâmpada 2', Color(153, 0, 255, 180)),
                LightSetting('Lâmpada 4', Color(153, 0, 255, 180)),
                LightSetting('Hue Iris', Color(255, 0, 102, 200)),
                LightSetting('Hue Play 1', Color(0, 255, 255, 100)),
                LightSetting('Hue Play 2', Color(0, 255, 255, 100)),
                LightSetting('Fita Led', Color(255, 153, 51, 120)),
                LightSetting('Led cima', Color(255, 255, 255, 60)),
            ]
        )


class GalacticAdventure(LightConfig):
    def __init__(self):
        super().__init__(
            "galactic_adventure",
            settings=[
                LightSetting('Lâmpada 1', Color(51, 153, 255, 180)),
                LightSetting('Lâmpada 2', Color(51, 153, 255, 180)),
                LightSetting('Lâmpada 4', Color(51, 153, 255, 180)),
                LightSetting('Hue Iris', Color(255, 255, 153, 200)),
                LightSetting('Hue Play 1', Color(102, 255, 102, 100)),
                LightSetting('Hue Play 2', Color(102, 255, 102, 100)),
                LightSetting('Fita Led', Color(255, 51, 153, 120)),
                LightSetting('Led cima', Color(255, 255, 255, 60)),
            ]
        )


class ElectricDreams(LightConfig):
    def __init__(self):
        super().__init__(
            "electric_dreams",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 51, 153, 180)),
                LightSetting('Lâmpada 2', Color(255, 51, 153, 180)),
                LightSetting('Lâmpada 4', Color(255, 51, 153, 180)),
                LightSetting('Hue Iris', Color(0, 255, 255, 200)),
                LightSetting('Hue Play 1', Color(255, 255, 102, 100)),
                LightSetting('Hue Play 2', Color(255, 255, 102, 100)),
                LightSetting('Fita Led', Color(102, 255, 102, 120)),
                LightSetting('Led cima', Color(255, 255, 255, 60)),
            ]
        )


class FuturisticLaserShow(LightConfig):
    def __init__(self):
        super().__init__(
            "futuristic_laser_show",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 0, 255, 200)),
                LightSetting('Lâmpada 2', Color(0, 255, 255, 200)),
                LightSetting('Lâmpada 4', Color(255, 0, 0, 200)),
                LightSetting('Hue Iris', Color(0, 0, 255, 150)),
                LightSetting('Hue Play 1', Color(0, 255, 0, 150)),
                LightSetting('Hue Play 2', Color(255, 255, 0, 150)),
                LightSetting('Fita Led', Color(255, 0, 255, 100)),
                LightSetting('Led cima', Color(255, 255, 255, 100)),
            ]
        )


class CheerfulPinkParty(LightConfig):
    def __init__(self):
        super().__init__(
            "cheerful_pink_party",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 105, 180, 200)),
                LightSetting('Lâmpada 2', Color(255, 182, 193, 200)),
                LightSetting('Lâmpada 4', Color(255, 20, 147, 200)),
                LightSetting('Hue Iris', Color(199, 21, 133, 150)),
                LightSetting('Hue Play 1', Color(255, 192, 203, 150)),
                LightSetting('Hue Play 2', Color(255, 105, 180, 150)),
                LightSetting('Fita Led', Color(255, 182, 193, 100)),
                LightSetting('Led cima', Color(255, 20, 147, 100)),
            ]
        )


class TranquilRoseGarden(LightConfig):
    def __init__(self):
        super().__init__(
            "tranquil_rose_garden",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 192, 203, 200)),
                LightSetting('Lâmpada 2', Color(255, 182, 193, 200)),
                LightSetting('Lâmpada 4', Color(255, 240, 245, 150)),
                LightSetting('Hue Iris', Color(255, 105, 180, 200)),
                LightSetting('Hue Play 1', Color(255, 228, 225, 150)),
                LightSetting('Hue Play 2', Color(255, 222, 173, 150)),
                LightSetting('Fita Led', Color(255, 105, 180, 100)),
                LightSetting('Led cima', Color(152, 251, 152, 100)),  # Tom de verde atualizado
            ]
        )


class GoldenSunset(LightConfig):
    def __init__(self):
        super().__init__(
            "golden_sunset",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 140, 0, 200)),
                LightSetting('Lâmpada 2', Color(255, 165, 0, 200)),
                LightSetting('Lâmpada 4', Color(255, 69, 0, 150)),
                LightSetting('Hue Iris', Color(255, 99, 71, 200)),
                LightSetting('Hue Play 1', Color(255, 105, 180, 150)),
                LightSetting('Hue Play 2', Color(255, 20, 147, 150)),
                LightSetting('Fita Led', Color(255, 160, 122, 100)),
                LightSetting('Led cima', Color(255, 215, 0, 100)),
            ]
        )


class TropicalSunset(LightConfig):
    def __init__(self):
        super().__init__(
            "tropical_sunset",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 99, 71, 200)),
                LightSetting('Lâmpada 2', Color(255, 140, 0, 200)),
                LightSetting('Lâmpada 4', Color(255, 165, 0, 150)),
                LightSetting('Hue Iris', Color(255, 69, 0, 200)),
                LightSetting('Hue Play 1', Color(255, 255, 0, 150)),
                LightSetting('Hue Play 2', Color(255, 215, 0, 150)),
                LightSetting('Fita Led', Color(255, 160, 122, 100)),
                LightSetting('Led cima', Color(255, 105, 180, 100)),
            ]
        )


class DesertSunset(LightConfig):
    def __init__(self):
        super().__init__(
            "desert_sunset",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 69, 0, 200)),
                LightSetting('Lâmpada 2', Color(255, 99, 71, 200)),
                LightSetting('Lâmpada 4', Color(255, 105, 180, 150)),
                LightSetting('Hue Iris', Color(255, 20, 147, 200)),
                LightSetting('Hue Play 1', Color(255, 160, 122, 150)),
                LightSetting('Hue Play 2', Color(255, 140, 0, 150)),
                LightSetting('Fita Led', Color(255, 165, 0, 100)),
                LightSetting('Led cima', Color(255, 215, 0, 100)),
            ]
        )
