"""Shared Imperial/Metric display-unit context, so the Designer (app.py) and the
Browse view (browse.py) convert values to the chosen unit the SAME way.

Everything in the app is stored and computed in SI base units — lengths in METERS,
mass in KG, force in N, specific (per-mass) force in N/kg, pressure in bar. A `Units`
object turns a "Metric"/"Imperial" choice into the display factors, labels, and
formatters used on the way out. Reverse has its own cylinder-specific unit handling
and does not use this.
"""


class Units:
    """Display factors/labels for one Metric|Imperial choice (+ a Fine-precision flag).

    Attributes mirror the names the Designer has always used:
      imperial, U/ULABEL/UWORD (length), MU/MLABEL (mass), PU/PLABEL (specific force),
      FU/FLABEL (total force), LEN_STEP/LEN_FMT/ROUND_DP (widget precision).
    Methods pk()/total()/mass() format a base-unit value as a labelled string.
    """

    def __init__(self, units, fine=False):
        self.imperial = imp = units == "Imperial"
        self.U = 39.3700787 if imp else 1.0        # meters -> display length
        self.ULABEL = "in" if imp else "m"          # short length label
        self.UWORD = "inches" if imp else "meters"
        self.MU = 2.2046226 if imp else 1.0        # kg -> display mass
        self.MLABEL = "lb" if imp else "kg"
        self.PU = 0.10197162 if imp else 1.0       # N/kg -> display specific force
        self.PLABEL = "lbf/lb" if imp else "N/kg"
        self.FU = 0.224809 if imp else 0.001       # N -> display total force (lbf / kN)
        self.FLABEL = "lbf" if imp else "kN"
        if imp:
            self.LEN_STEP, self.LEN_FMT = (0.01, "%.3f") if fine else (0.1, "%.2f")
        else:
            self.LEN_STEP, self.LEN_FMT = (0.001, "%.3f") if fine else (0.01, "%.2f")
        self.ROUND_DP = 3 if fine else 2           # meters precision the optimize snaps to

    def pk(self, nkg):
        """A specific / peak force (base N/kg) as a labelled display string."""
        return f"{nkg * self.PU:.2f} {self.PLABEL}"

    def total(self, newtons):
        """A total force (base newtons) as a labelled display string (lbf or kN).
        Decimals scale with magnitude so small values (light scale-model walls)
        keep useful precision while large values stay readable."""
        if self.imperial:
            v = newtons * 0.224809
            dp = 0 if abs(v) >= 100 else 1 if abs(v) >= 10 else 2
            return f"{v:,.{dp}f} lbf"
        v = newtons / 1000
        dp = 1 if abs(v) >= 100 else 2 if abs(v) >= 10 else 3
        return f"{v:,.{dp}f} kN"

    def mass(self, kg):
        """A mass (base kg) as a labelled display string (lb or kg)."""
        return f"{kg * self.MU:,.0f} {self.MLABEL}"

    def length(self, m, dp=2):
        """A length (base meters) as a labelled display string (in or m)."""
        return f"{m * self.U:.{dp}f} {self.ULABEL}"
