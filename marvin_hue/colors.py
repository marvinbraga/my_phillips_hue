import random


class Color:
    """
    Classe para guardar as configurações de cores.

    Atributos:
        red (int): Valor vermelho (0-255)
        green (int): Valor verde (0-255)
        blue (int): Valor azul (0-255)
        brightness (int): Brilho (0-254)

    Raises:
        ValueError: Se algum valor estiver fora dos limites permitidos
    """

    def __init__(
        self, red: int = 254, green: int = 254, blue: int = 254, brightness: int = 254
    ):
        # Validação RGB: 0-255
        if not isinstance(red, int) or not 0 <= red <= 255:
            raise ValueError(
                f"Valor de red deve ser inteiro entre 0-255, recebido: {red}"
            )
        if not isinstance(green, int) or not 0 <= green <= 255:
            raise ValueError(
                f"Valor de green deve ser inteiro entre 0-255, recebido: {green}"
            )
        if not isinstance(blue, int) or not 0 <= blue <= 255:
            raise ValueError(
                f"Valor de blue deve ser inteiro entre 0-255, recebido: {blue}"
            )

        # Validação Brightness: 0-254
        if not isinstance(brightness, int) or not 0 <= brightness <= 254:
            raise ValueError(
                f"Valor de brightness deve ser inteiro entre 0-254, recebido: {brightness}"
            )

        self.red = red
        self.green = green
        self.blue = blue
        self.brightness = brightness

    def __str__(self) -> str:
        return f"R: {self.red}, G: {self.green}, B: {self.blue}, Brightness: {self.brightness}"

    def to_dict(self) -> dict[str, int]:
        """Converte a cor para dicionário."""
        return {
            "red": self.red,
            "green": self.green,
            "blue": self.blue,
            "brightness": self.brightness,
        }

    @staticmethod
    def random_color(brightness: int = 254) -> "Color":
        """
        Gera uma cor aleatória.

        Args:
            brightness: Brilho desejado (0-254), ou 254 para brilho aleatório

        Returns:
            Color: Nova cor aleatória
        """
        red = random.randint(0, 255)
        green = random.randint(0, 255)
        blue = random.randint(0, 255)
        brightness = random.randint(0, 254) if brightness == 254 else brightness
        return Color(red, green, blue, brightness)
