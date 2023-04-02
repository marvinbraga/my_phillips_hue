class RGBtoXYAdapter:
    @staticmethod
    def convert(red, green, blue):
        if red > 0.04045:
            red = ((red + 0.055) / (1.0 + 0.055)) ** 2.4
        else:
            red = red / 12.92

        if green > 0.04045:
            green = ((green + 0.055) / (1.0 + 0.055)) ** 2.4
        else:
            green = green / 12.92

        if blue > 0.04045:
            blue = ((blue + 0.055) / (1.0 + 0.055)) ** 2.4
        else:
            blue = blue / 12.92

        X = red * 0.664511 + green * 0.154324 + blue * 0.162028
        Y = red * 0.283881 + green * 0.668433 + blue * 0.047685
        Z = red * 0.000088 + green * 0.072310 + blue * 0.986039

        x = X / (X + Y + Z)
        y = Y / (X + Y + Z)
        return x, y
