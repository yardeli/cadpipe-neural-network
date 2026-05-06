"""Physical constants. NIST 2019 SI definitions where applicable."""

K_B = 1.380649e-23           # Boltzmann (J/K)
M_E = 9.1093837015e-31       # electron mass (kg)
E_CHARGE = 1.602176634e-19   # elementary charge (C)
EPS_0 = 8.8541878128e-12     # vacuum permittivity (F/m)
H_PLANCK = 6.62607015e-34    # Planck (J·s)
C_LIGHT = 2.99792458e8       # speed of light (m/s)
N_AV = 6.02214076e23         # Avogadro
R_GAS = 8.314462618          # universal gas constant (J/mol/K)

# Air-specific (mixture-averaged for N2/O2 at sea level)
GAMMA_AIR = 1.4
M_AIR = 0.0289644            # molar mass dry air (kg/mol)
R_AIR = R_GAS / M_AIR        # 287.05 J/(kg·K)
CP_AIR_PG = GAMMA_AIR * R_AIR / (GAMMA_AIR - 1.0)  # 1004.5 J/kg/K

# Ionization energies (NIST ASD, eV)
EI_NO_eV = 9.26438
EI_O_eV = 13.61806
EI_N_eV = 14.53414

# Earth gravity (USSA76)
G_EARTH = 9.80665            # m/s² (standard gravity)
