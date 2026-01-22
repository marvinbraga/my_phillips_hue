from functools import lru_cache


class ColorConverter:
    """
    Centraliza conversões de espaço de cor para Philips Hue.

    Suporta conversões bidirecionais:
    - RGB -> XY (para enviar cores para a bridge)
    - XY -> RGB (para exibir cores da bridge)
    """

    @staticmethod
    @lru_cache(maxsize=256)
    def rgb_to_xy(red: int, green: int, blue: int) -> tuple[float, float]:
        """
        Converte RGB para XY.

        O processo de conversão:
        1. Normaliza RGB (0-255) para (0-1)
        2. Aplica correção gamma reversa (sRGB -> linear RGB)
        3. Converte RGB linear para CIE XYZ usando matriz de transformação
        4. Calcula coordenadas de cromaticidade xy a partir de XYZ

        Args:
            red: Valor vermelho (0-255)
            green: Valor verde (0-255)
            blue: Valor azul (0-255)

        Returns:
            tuple[float, float]: Coordenadas (x, y) no espaço de cor Hue

        Raises:
            ValueError: Se valores RGB estiverem fora do intervalo 0-255
        """
        # Validação de entrada
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

        # Normaliza RGB para 0-1
        red_norm = red / 255.0
        green_norm = green / 255.0
        blue_norm = blue / 255.0

        # Aplica correção gamma reversa (sRGB -> linear RGB)
        if red_norm > 0.04045:
            red_linear = ((red_norm + 0.055) / (1.0 + 0.055)) ** 2.4
        else:
            red_linear = red_norm / 12.92

        if green_norm > 0.04045:
            green_linear = ((green_norm + 0.055) / (1.0 + 0.055)) ** 2.4
        else:
            green_linear = green_norm / 12.92

        if blue_norm > 0.04045:
            blue_linear = ((blue_norm + 0.055) / (1.0 + 0.055)) ** 2.4
        else:
            blue_linear = blue_norm / 12.92

        # Converte RGB linear para CIE XYZ usando matriz Wide RGB D65
        X = red_linear * 0.664511 + green_linear * 0.154324 + blue_linear * 0.162028
        Y = red_linear * 0.283881 + green_linear * 0.668433 + blue_linear * 0.047685
        Z = red_linear * 0.000088 + green_linear * 0.072310 + blue_linear * 0.986039

        # Calcula coordenadas de cromaticidade xy
        # Protege contra divisão por zero
        xyz_sum = X + Y + Z
        if xyz_sum < 0.00001:
            # Retorna branco se a soma for zero
            return (0.3127, 0.3290)

        x = X / xyz_sum
        y = Y / xyz_sum
        return (x, y)

    @staticmethod
    def xy_to_rgb(
        xy: tuple[float, float], brightness: int = 254
    ) -> tuple[int, int, int]:
        """
        Converte coordenadas XY do Hue para RGB.

        Args:
            xy: Tupla com coordenadas (x, y) do espaço de cor Hue
            brightness: Brilho da lâmpada (0-254)

        Returns:
            tuple[int, int, int]: Valores RGB (0-255)
        """
        x, y = xy
        z = 1.0 - x - y

        # Evitar divisão por zero
        if y == 0:
            y = 0.00001

        Y = brightness / 254.0
        X = (Y / y) * x
        Z = (Y / y) * z

        # Converter XYZ para RGB usando matriz inversa
        r = X * 1.656492 - Y * 0.354851 - Z * 0.255038
        g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152
        b = X * 0.051713 - Y * 0.121364 + Z * 1.011530

        # Aplicar correção gamma
        def gamma_correct(value: float) -> float:
            if value <= 0.0031308:
                return float(12.92 * value)
            return float((1.0 + 0.055) * pow(value, (1.0 / 2.4)) - 0.055)

        r = gamma_correct(r)
        g = gamma_correct(g)
        b = gamma_correct(b)

        # Normalizar e converter para 0-255
        max_val = max(r, g, b, 1)
        r = int(max(0, min(255, (r / max_val) * 255)))
        g = int(max(0, min(255, (g / max_val) * 255)))
        b = int(max(0, min(255, (b / max_val) * 255)))

        return (r, g, b)


class RGBtoXYAdapter:
    """
    DEPRECATED: Use ColorConverter.rgb_to_xy() instead.

    Mantido para compatibilidade retroativa. Será removido em versão futura.
    """

    @staticmethod
    def convert(red: int, green: int, blue: int) -> tuple[float, float]:
        """
        DEPRECATED: Use ColorConverter.rgb_to_xy() instead.

        Args:
            red: Valor vermelho (0-255)
            green: Valor verde (0-255)
            blue: Valor azul (0-255)

        Returns:
            tuple[float, float]: Coordenadas (x, y) no espaço de cor Hue

        Raises:
            ValueError: Se valores RGB estiverem fora do intervalo 0-255
        """
        return ColorConverter.rgb_to_xy(red, green, blue)
