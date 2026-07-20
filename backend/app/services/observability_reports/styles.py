"""Centralised Wazza report design tokens."""

PRIMARY = (16, 125, 96)
SUCCESS = (22, 132, 89)
WARNING = (202, 138, 4)
CRITICAL = (190, 24, 93)
TEXT = (24, 35, 51)
MUTED = (100, 116, 139)
BORDER = (226, 232, 240)
SUBTLE = (248, 250, 252)
WHITE = (255, 255, 255)
# Editorial spacing scale.  Layout code must use these tokens rather than
# sprinkling coordinate literals through report sections.
SPACE_2XS = 4
SPACE_XS = 8
SPACE_SM = 12
SPACE_MD = 18
SPACE_LG = 24
SPACE_XL = 32
SPACE_2XL = 44
SPACING = SPACE_SM
RADIUS = 7
FONT = {"title": 25, "heading": 16, "body": 9, "small": 8, "kpi": 19}
