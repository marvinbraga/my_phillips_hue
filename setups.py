from colors import Color


class LightSetting:
    def __init__(self, light_name, color: Color):
        self.light_name = light_name
        self.color = color


class LightConfig:
    def __init__(self, name, settings):
        self.name = name
        self.settings: list[LightSetting] = settings


class __init__(LightConfig):
    def __init__(self):
        super().__init__(
            "brilho_cores",
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
        super().__init__(
            "concentracao",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 255, 255, 255)),
                LightSetting('Lâmpada 2', Color(255, 255, 255, 255)),
                LightSetting('Lâmpada 4', Color(255, 255, 255, 255)),
                LightSetting('Hue Iris', Color(255, 255, 255, 130)),
                LightSetting('Hue Play 1', Color(255, 255, 255, 100)),
                LightSetting('Hue Play 2', Color(255, 255, 255, 100)),
                LightSetting('Fita Led', Color(255, 255, 255, 80)),
                LightSetting('Led cima', Color(255, 255, 255, 40)),
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


class LightConfig1(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 1",
            settings=[
                LightSetting('Lâmpada 1', Color(255, 230, 220, 170)),
                LightSetting('Lâmpada 2', Color(255, 230, 220, 170)),
                LightSetting('Lâmpada 4', Color(255, 230, 220, 170)),
                LightSetting('Hue Iris', Color(150, 255, 200, 130)),
                LightSetting('Hue Play 1', Color(200, 255, 230, 100)),
                LightSetting('Hue Play 2', Color(200, 255, 230, 100)),
                LightSetting('Fita Led', Color(255, 200, 150, 80)),
                LightSetting('Led cima', Color(200, 255, 255, 40)),
            ]
        )


class LightConfig2(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 2",
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


class LightConfig3(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 3",
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


class LightConfig4(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 4",
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


class LightConfig5(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 5",
            settings=[
                LightSetting('Lâmpada 1', Color(240, 255, 255, 170)),
                LightSetting('Lâmpada 2', Color(240, 255, 255, 170)),
                LightSetting('Lâmpada 4', Color(240, 255, 255, 170)),
                LightSetting('Hue Iris', Color(140, 255, 230, 130)),
                LightSetting('Hue Play 1', Color(240, 255, 140, 100)),
                LightSetting('Hue Play 2', Color(240, 255, 140, 100)),
                LightSetting('Fita Led', Color(200, 255, 150, 80)),
                LightSetting('Led cima', Color(255, 244, 229, 40)),
            ]
        )


class LightConfig6(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 6",
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


class LightConfig7(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 7",
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


class LightConfig8(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 8",
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


class LightConfig9(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 9",
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


class LightConfig10(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 10",
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


class LightConfig11(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 11",
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


class LightConfig12(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 12",
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


class LightConfig13(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 13",
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


class LightConfig14(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 14",
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


class LightConfig15(LightConfig):
    def __init__(self):
        super().__init__(
            "Configuração 15",
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


class Setups:

    def __init__(self):
        self.list = [
            __init__(),
            SetupConcentration(),
            SetupFuturistic(),
            SetupRelaxing(),
            SetupStudy(),
            SetupEntertainment(),
            LightConfig1(),
            LightConfig2(),
            LightConfig3(),
            LightConfig4(),
            LightConfig5(),
            LightConfig6(),
            LightConfig7(),
            LightConfig8(),
            LightConfig9(),
            LightConfig10(),
            LightConfig11(),
            LightConfig12(),
            LightConfig13(),
            LightConfig14(),
            LightConfig15(),
        ]

    def get(self, name):
        return [setup for setup in self.list if setup.name == name][0]

    def list_names(self):
        return [setup.name for setup in self.list]
