"""Auditable chemistry data, independent of the animation renderer."""
import hashlib
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NIST_URL = ('https://physics.nist.gov/cgi-bin/ASD/ie.pl?spectra=H-Ca%20I&units=1&format=1'
            '&order=0&at_num_out=on&sp_name_out=on&ion_charge_out=on&el_name_out=on'
            '&shells_out=on&e_out=0&unc_out=on&biblio=on')
SYMBOLS = ('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
           'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba '
           'La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn '
           'Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og').split()
KOREAN = ('수소 헬륨 리튬 베릴륨 붕소 탄소 질소 산소 플루오린 네온 나트륨 마그네슘 '
          '알루미늄 규소 인 황 염소 아르곤 칼륨 칼슘').split()
CAPACITY = {'s': 2, 'p': 6, 'd': 10, 'f': 14}
ORDER = ['1s', '2s', '2p', '3s', '3p', '4s']


def configuration(z):
    """Only H–Ca: do not extrapolate this elementary filling model to d/f atoms."""
    if not 1 <= z <= 20:
        raise ValueError('Detailed model is restricted to neutral ground-state H–Ca')
    remaining, result = z, {}
    for orb in ORDER:
        n = min(CAPACITY[orb[-1]], remaining)
        result[orb] = n
        remaining -= n
    return result


def occupation(n, orbitals):
    """Spin occupations: Hund first, then opposite-spin pairing."""
    if not 0 <= n <= 2*orbitals:
        raise ValueError('Subshell overfilled')
    return [(int(n > j), int(n > orbitals+j)) for j in range(orbitals)]


def elements():
    rows = [(1, [1, 2], [1, 18]),
            (2, list(range(3, 11)), [1, 2, 13, 14, 15, 16, 17, 18]),
            (3, list(range(11, 19)), [1, 2, 13, 14, 15, 16, 17, 18]),
            (4, list(range(19, 37)), list(range(1, 19))),
            (5, list(range(37, 55)), list(range(1, 19))),
            (6, [55, 56]+list(range(72, 87)), [1, 2]+list(range(4, 19))),
            (7, [87, 88]+list(range(104, 119)), [1, 2]+list(range(4, 19))),
            (9, list(range(57, 72)), list(range(3, 18))),
            (10, list(range(89, 104)), list(range(3, 18)))]
    result = []
    for row, zs, cols in rows:
        for z, col in zip(zs, cols, strict=True):
            # Detached series are NOT labelled as 15 f orbitals / f electrons.
            block = 'series' if row >= 9 else 's' if col <= 2 or z == 2 else 'p' if col >= 13 else 'd'
            result.append(dict(z=z, symbol=SYMBOLS[z-1], row=row, col=col,
                               block=block, name=KOREAN[z-1] if z <= 20 else SYMBOLS[z-1]))
    return sorted(result, key=lambda e: e['z'])


def nist():
    content = (ROOT/'data'/'nist-h-ca.html').read_text()
    pre = re.search(r'<pre>(.*?)</pre>', content, re.S).group(1)
    lines = html.unescape(re.sub(r'<[^>]+>', '', pre)).splitlines()
    result = []
    for line in lines:
        if not re.match(r'^\s*\d+\s*\|', line):
            continue
        cols = [c.strip() for c in line.split('|')]
        result.append(dict(z=int(cols[0]), symbol=cols[1].split()[0], charge=int(cols[2]),
                           name=cols[3], configuration=cols[4],
                           ionization_eV=float(re.search(r'[\d.]+', cols[5]).group()),
                           reported_energy=cols[5], uncertainty_eV=cols[6], references=cols[7]))
    return result


def expand_configuration(value):
    value = value.replace('[Ne]', '1s2.2s2.2p6').replace('[Ar]', '1s2.2s2.2p6.3s2.3p6')
    return {orb: int(n or 1) for orb, n in re.findall(r'(\d[spdf])(\d*)', value)}


def verify():
    es, measurements = elements(), nist()
    assert len(es) == len(SYMBOLS) == len(set(SYMBOLS)) == 118
    assert [e['z'] for e in es] == list(range(1, 119))
    assert len({(e['row'], e['col']) for e in es}) == 118
    assert [r['z'] for r in measurements] == list(range(1, 21))
    for r in measurements:
        assert r['charge'] == 0 and r['symbol'] == SYMBOLS[r['z']-1]
        model = {k:v for k,v in configuration(r['z']).items() if v}
        assert model == expand_configuration(r['configuration']), (r, model)
        assert sum(model.values()) == r['z']
        for orb, n in model.items():
            assert n <= CAPACITY[orb[-1]]
            assert sum(sum(pair) for pair in occupation(n, CAPACITY[orb[-1]]//2)) == n
    energies = {r['z']:r['ionization_eV'] for r in measurements}
    assert energies[2] > energies[3] and energies[10] > energies[11] and energies[18] > energies[19]
    assert energies[4] > energies[5] and energies[7] > energies[8]
    assert energies[12] > energies[13] and energies[15] > energies[16]
    assert energies[19] < energies[11] < energies[3]
    assert es[1]['col'] == 18 and es[1]['block'] == 's'
    assert configuration(18)['3p'] == 6 and configuration(19)['4s'] == 1
    assert CAPACITY == {'s':2, 'p':6, 'd':10, 'f':14}
    return dict(elements=118, nist_ground_states_verified=20, ionization_data='NIST ASD 5.12, eV',
                exceptions_preserved=['Be > B', 'N > O', 'Mg > Al', 'P > S'],
                detailed_configuration_range='neutral H–Ca',
                nist_snapshot_sha256=hashlib.sha256((ROOT/'data'/'nist-h-ca.html').read_bytes()).hexdigest())


def export():
    validation = verify()
    data = dict(elements=elements(), nist_ground_states=nist(), capacities=CAPACITY,
                source_url=NIST_URL, retrieved='2026-10-05', validation=validation)
    (ROOT/'facts.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    return validation


if __name__ == '__main__':
    print(json.dumps(export(), ensure_ascii=False, indent=2))
