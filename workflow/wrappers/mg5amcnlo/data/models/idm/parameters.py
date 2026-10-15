# This file was automatically created by FeynRules 2.3.2
# Mathematica version: 8.0 for Linux x86 (64-bit) (February 23, 2011)
# Date: Sun 7 Aug 2016 10:05:39



from object_library import all_parameters, Parameter


from function_library import complexconjugate, re, im, csc, sec, acsc, asec, cot

# This is a default parameter object representing 0.
ZERO = Parameter(name = 'ZERO',
                 nature = 'internal',
                 type = 'real',
                 value = '0.0',
                 texname = '0')

# User-defined parameters.
cabi = Parameter(name = 'cabi',
                 nature = 'external',
                 type = 'real',
                 value = 0.227736,
                 texname = '\\theta _c',
                 lhablock = 'CKMBLOCK',
                 lhacode = [ 1 ])

aEWM1 = Parameter(name = 'aEWM1',
                  nature = 'external',
                  type = 'real',
                  value = 128.9,
                  texname = '\\text{aEWM1}',
                  lhablock = 'FRBlock',
                  lhacode = [ 1 ])

Gf = Parameter(name = 'Gf',
               nature = 'external',
               type = 'real',
               value = 0.0000116637,
               texname = 'G_F',
               lhablock = 'FRBlock',
               lhacode = [ 2 ])

aS = Parameter(name = 'aS',
               nature = 'external',
               type = 'real',
               value = 0.1172,
               texname = '\\alpha _s',
               lhablock = 'FRBlock',
               lhacode = [ 3 ])

QS = Parameter(name = 'QS',
               nature = 'external',
               type = 'real',
               value = 100.,
               texname = 'Q_s',
               lhablock = 'FRBlock',
               lhacode = [ 4 ])

lamL = Parameter(name = 'lamL',
                 nature = 'external',
                 type = 'real',
                 value = 0.0001,
                 texname = '\\lambda _L',
                 lhablock = 'FRBlock',
                 lhacode = [ 5 ])

lam2 = Parameter(name = 'lam2',
                 nature = 'external',
                 type = 'real',
                 value = 0.0005,
                 texname = '\\lambda _2',
                 lhablock = 'FRBlock',
                 lhacode = [ 6 ])

Me = Parameter(name = 'Me',
               nature = 'external',
               type = 'real',
               value = 0.000511,
               texname = '\\text{Me}',
               lhablock = 'MASS',
               lhacode = [ 11 ])

MM = Parameter(name = 'MM',
               nature = 'external',
               type = 'real',
               value = 0.1057,
               texname = '\\text{MM}',
               lhablock = 'MASS',
               lhacode = [ 13 ])

MTA = Parameter(name = 'MTA',
                nature = 'external',
                type = 'real',
                value = 1.777,
                texname = '\\text{MTA}',
                lhablock = 'MASS',
                lhacode = [ 15 ])

MU = Parameter(name = 'MU',
               nature = 'external',
               type = 'real',
               value = 0.00255,
               texname = 'M',
               lhablock = 'MASS',
               lhacode = [ 2 ])

MC = Parameter(name = 'MC',
               nature = 'external',
               type = 'real',
               value = 1.27,
               texname = '\\text{MC}',
               lhablock = 'MASS',
               lhacode = [ 4 ])

MT = Parameter(name = 'MT',
               nature = 'external',
               type = 'real',
               value = 172,
               texname = '\\text{MT}',
               lhablock = 'MASS',
               lhacode = [ 6 ])

MD = Parameter(name = 'MD',
               nature = 'external',
               type = 'real',
               value = 0.00504,
               texname = '\\text{MD}',
               lhablock = 'MASS',
               lhacode = [ 1 ])

MS = Parameter(name = 'MS',
               nature = 'external',
               type = 'real',
               value = 0.1,
               texname = '\\text{MS}',
               lhablock = 'MASS',
               lhacode = [ 3 ])

MB = Parameter(name = 'MB',
               nature = 'external',
               type = 'real',
               value = 4.7,
               texname = '\\text{MB}',
               lhablock = 'MASS',
               lhacode = [ 5 ])

MZ = Parameter(name = 'MZ',
               nature = 'external',
               type = 'real',
               value = 91.1876,
               texname = '\\text{MZ}',
               lhablock = 'MASS',
               lhacode = [ 23 ])

mh = Parameter(name = 'mh',
               nature = 'external',
               type = 'real',
               value = 125.,
               texname = '\\text{mh}',
               lhablock = 'MASS',
               lhacode = [ 25 ])

MH0 = Parameter(name = 'MH0',
                nature = 'external',
                type = 'real',
                value = 100,
                texname = '\\text{MH0}',
                lhablock = 'MASS',
                lhacode = [ 35 ])

MA0 = Parameter(name = 'MA0',
                nature = 'external',
                type = 'real',
                value = 100,
                texname = '\\text{MA0}',
                lhablock = 'MASS',
                lhacode = [ 36 ])

MHch = Parameter(name = 'MHch',
                 nature = 'external',
                 type = 'real',
                 value = 100,
                 texname = '\\text{MHch}',
                 lhablock = 'MASS',
                 lhacode = [ 37 ])

WT = Parameter(name = 'WT',
               nature = 'external',
               type = 'real',
               value = 2.,
               texname = '\\text{WT}',
               lhablock = 'DECAY',
               lhacode = [ 6 ])

WZ = Parameter(name = 'WZ',
               nature = 'external',
               type = 'real',
               value = 2.4952,
               texname = '\\text{WZ}',
               lhablock = 'DECAY',
               lhacode = [ 23 ])

WW = Parameter(name = 'WW',
               nature = 'external',
               type = 'real',
               value = 2.085,
               texname = '\\text{WW}',
               lhablock = 'DECAY',
               lhacode = [ 24 ])

Wh = Parameter(name = 'Wh',
               nature = 'external',
               type = 'real',
               value = 1.,
               texname = '\\text{Wh}',
               lhablock = 'DECAY',
               lhacode = [ 25 ])

WH0 = Parameter(name = 'WH0',
                nature = 'external',
                type = 'real',
                value = 0.,
                texname = '\\text{WH0}',
                lhablock = 'DECAY',
                lhacode = [ 35 ])

WA0 = Parameter(name = 'WA0',
                nature = 'external',
                type = 'real',
                value = 1.,
                texname = '\\text{WA0}',
                lhablock = 'DECAY',
                lhacode = [ 36 ])

WHch = Parameter(name = 'WHch',
                 nature = 'external',
                 type = 'real',
                 value = 1.,
                 texname = '\\text{WHch}',
                 lhablock = 'DECAY',
                 lhacode = [ 37 ])

aEW = Parameter(name = 'aEW',
                nature = 'internal',
                type = 'real',
                value = '1./aEWM1',
                texname = '\\text{aEW}')

CKM1x1 = Parameter(name = 'CKM1x1',
                   nature = 'internal',
                   type = 'complex',
                   value = 'cmath.cos(cabi)',
                   texname = '\\text{CKM1x1}')

CKM1x2 = Parameter(name = 'CKM1x2',
                   nature = 'internal',
                   type = 'complex',
                   value = 'cmath.sin(cabi)',
                   texname = '\\text{CKM1x2}')

CKM1x3 = Parameter(name = 'CKM1x3',
                   nature = 'internal',
                   type = 'complex',
                   value = '0',
                   texname = '\\text{CKM1x3}')

CKM2x1 = Parameter(name = 'CKM2x1',
                   nature = 'internal',
                   type = 'complex',
                   value = '-cmath.sin(cabi)',
                   texname = '\\text{CKM2x1}')

CKM2x2 = Parameter(name = 'CKM2x2',
                   nature = 'internal',
                   type = 'complex',
                   value = 'cmath.cos(cabi)',
                   texname = '\\text{CKM2x2}')

CKM2x3 = Parameter(name = 'CKM2x3',
                   nature = 'internal',
                   type = 'complex',
                   value = '0',
                   texname = '\\text{CKM2x3}')

CKM3x1 = Parameter(name = 'CKM3x1',
                   nature = 'internal',
                   type = 'complex',
                   value = '0',
                   texname = '\\text{CKM3x1}')

CKM3x2 = Parameter(name = 'CKM3x2',
                   nature = 'internal',
                   type = 'complex',
                   value = '0',
                   texname = '\\text{CKM3x2}')

CKM3x3 = Parameter(name = 'CKM3x3',
                   nature = 'internal',
                   type = 'complex',
                   value = '1',
                   texname = '\\text{CKM3x3}')

G = Parameter(name = 'G',
              nature = 'internal',
              type = 'real',
              value = '2*cmath.sqrt(aS)*cmath.sqrt(cmath.pi)',
              texname = 'G')

mu1 = Parameter(name = 'mu1',
                nature = 'internal',
                type = 'complex',
                value = 'cmath.sqrt(-mh**2)/cmath.sqrt(2)',
                texname = '\\mu _1')


MW = Parameter(name = 'MW',
               nature = 'internal',
               type = 'real',
               value = 'cmath.sqrt(MZ**2/2. + cmath.sqrt(MZ**4/4. - (aEW*cmath.pi*MZ**2)/(Gf*cmath.sqrt(2))))',
               texname = '\\text{MW}')

ee = Parameter(name = 'ee',
               nature = 'internal',
               type = 'real',
               value = '2*cmath.sqrt(aEW)*cmath.sqrt(cmath.pi)',
               texname = 'e')

CW2 = Parameter(name = 'CW2',
                nature = 'internal',
                type = 'real',
                value = 'MW**2/MZ**2',
                texname = 'c_w^2')

CW = Parameter(name = 'CW',
               nature = 'internal',
               type = 'real',
               value = 'cmath.sqrt(CW2)',
               texname = 'c_w')

SW2 = Parameter(name = 'SW2',
                nature = 'internal',
                type = 'real',
                value = '1 - CW2',
                texname = 's_w^2')

SW = Parameter(name = 'SW',
               nature = 'internal',
               type = 'real',
               value = 'cmath.sqrt(SW2)',
               texname = 's_w')

g1 = Parameter(name = 'g1',
               nature = 'internal',
               type = 'real',
               value = 'ee/CW',
               texname = 'g_1')

g2 = Parameter(name = 'g2',
               nature = 'internal',
               type = 'real',
               value = 'ee/SW',
               texname = 'g_2')

v = Parameter(name = 'v',
              nature = 'internal',
              type = 'real',
              value = '(2*MW*SW)/ee',
              texname = 'v')

mu2 = Parameter(name = 'mu2',
                nature = 'internal',
                type = 'real',
                value = 'cmath.sqrt(MH0**2 - lamL*v**2)',
                texname = '\\mu _2')

lam = Parameter(name = 'lam',
                nature = 'internal',
                type = 'real',
                value = 'mh**2/(2.*v**2)',
                texname = '\\lambda _1')

lam3 = Parameter(name = 'lam3',
                 nature = 'internal',
                 type = 'real',
                 value = '(2*(-MH0**2 + MHch**2 + lamL*v**2))/v**2',
                 texname = '\\lambda _3')

lam4 = Parameter(name = 'lam4',
                 nature = 'internal',
                 type = 'real',
                 value = '(MA0**2 + MH0**2 - 2*MHch**2)/v**2',
                 texname = '\\lambda _4')

lam5 = Parameter(name = 'lam5',
                 nature = 'internal',
                 type = 'real',
                 value = '(-MA0**2 + MH0**2)/v**2',
                 texname = '\\lambda _5')

yd1x1 = Parameter(name = 'yd1x1',
                  nature = 'internal',
                  type = 'real',
                  value = '(MD*cmath.sqrt(2))/v',
                  texname = '\\text{yd1x1}')

yd2x2 = Parameter(name = 'yd2x2',
                  nature = 'internal',
                  type = 'real',
                  value = '(MS*cmath.sqrt(2))/v',
                  texname = '\\text{yd2x2}')

yd3x3 = Parameter(name = 'yd3x3',
                  nature = 'internal',
                  type = 'real',
                  value = '(MB*cmath.sqrt(2))/v',
                  texname = '\\text{yd3x3}')

yl1x1 = Parameter(name = 'yl1x1',
                  nature = 'internal',
                  type = 'real',
                  value = '(Me*cmath.sqrt(2))/v',
                  texname = '\\text{yl1x1}')

yl2x2 = Parameter(name = 'yl2x2',
                  nature = 'internal',
                  type = 'real',
                  value = '(MM*cmath.sqrt(2))/v',
                  texname = '\\text{yl2x2}')

yl3x3 = Parameter(name = 'yl3x3',
                  nature = 'internal',
                  type = 'real',
                  value = '(MTA*cmath.sqrt(2))/v',
                  texname = '\\text{yl3x3}')

yu1x1 = Parameter(name = 'yu1x1',
                  nature = 'internal',
                  type = 'real',
                  value = '(MU*cmath.sqrt(2))/v',
                  texname = '\\text{yu1x1}')

yu2x2 = Parameter(name = 'yu2x2',
                  nature = 'internal',
                  type = 'real',
                  value = '(MC*cmath.sqrt(2))/v',
                  texname = '\\text{yu2x2}')

yu3x3 = Parameter(name = 'yu3x3',
                  nature = 'internal',
                  type = 'real',
                  value = '(MT*cmath.sqrt(2))/v',
                  texname = '\\text{yu3x3}')

Lambdaglu = Parameter(name = 'Lambdaglu',
                      nature = 'internal',
                      type = 'real',
                      value = '9.127296548027784*v',
                      texname = '\\Lambda _g')

Lambdagam = Parameter(name = 'Lambdagam',
                      nature = 'internal',
                      type = 'real',
                      value = '6.845472411020839*v',
                      texname = '\\Lambda _A')

