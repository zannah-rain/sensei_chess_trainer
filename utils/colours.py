def hex_to_rgb(hex_string):
    hex_string = hex_string.lstrip('#')
    return tuple(int(hex_string[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    return '#%02x%02x%02x' % rgb
