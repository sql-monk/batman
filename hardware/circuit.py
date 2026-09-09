from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class Part:
    ref: str
    value: str
    sheet: str
    pins: list
    kind: str = "block"
    board: str = ""
    position: tuple = (0, 0)
    footprint: str = ""
    alias: str = ""


def circuit():
    parts = []

    def add(ref, value, sheet, nets, kind="block", board="", position=(0, 0), names=None, types=None):
        names = names or [str(number + 1) for number in range(len(nets))]
        types = types or ["passive"] * len(nets)
        pins = [(str(number + 1), name, net, pin_type)
                for number, (name, net, pin_type) in enumerate(zip(names, nets, types))]
        part = Part(ref, value, sheet, pins, kind, board, position)
        parts.append(part)
        return part

    def resistor(ref, value, first, second, x, y, sheet="sense"):
        return add(ref, value, sheet, [first, second], "R", "A", (x, y))

    def capacitor(ref, value, first, second, x, y, sheet="sense", board="A", kind="C"):
        return add(ref, value, sheet, [first, second], kind, board, (x, y))

    left = ["3V3", "EN", "GPIO36", "GPIO39", "GPIO34", "GPIO35", "GPIO32", "GPIO33",
            "GPIO25", "GPIO26", "GPIO27", "GPIO14", "GPIO12", "GND", "GPIO13",
            "GPIO9", "GPIO10", "GPIO11", "VIN"]
    right = ["GND", "GPIO23", "GPIO22", "GPIO1", "GPIO3", "GPIO21", "GND", "GPIO19",
             "GPIO18", "GPIO5", "GPIO17", "GPIO16", "GPIO4", "GPIO0", "GPIO2",
             "GPIO15", "GPIO8", "GPIO7", "GPIO6"]
    gpio = {"3V3": "+3V3", "GND": "GND", "VIN": "+5V", "GPIO39": "I_LOAD",
            "GPIO34": "U_LOAD", "GPIO32": "BTN", "GPIO25": "SW1_ON",
            "GPIO26": "SW2_ON", "GPIO27": "K1", "GPIO33": "SENS_PWR", "GPIO13": "K2",
            "GPIO23": "MOSI", "GPIO22": "SCL", "GPIO21": "SDA", "GPIO19": "MISO",
            "GPIO18": "SCK", "GPIO5": "CS", "GPIO17": "DPS_TX", "GPIO16": "DPS_RX",
            "GPIO4": "OW"}
    pin_names = left + right
    pin_types = ["power_out" if name == "3V3" else "power_in" if name in ("GND", "VIN")
                 else "input" if name in ("GPIO34", "GPIO35", "GPIO36", "GPIO39")
                 else "bidirectional" for name in pin_names]
    add("J1", "DevKitC_38_socket_mMCU", "logic", [gpio.get(name) for name in pin_names],
        "MCU", "A", (8, 24), pin_names, pin_types)
    add("J2", "ADS1115_socket_mADC", "sense",
        ["+3V3", "GND", "SCL", "SDA", "GND", None, "I_B1", "I_B2", "U_B1", "U_B2"],
        "header_h", "A", (45, 28), ["VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"],
        ["power_in", "power_in", "input", "bidirectional", "input", "open_collector", "input", "input", "input", "input"])
    for index, y in enumerate([8, 15, 22], 1):
        raw = f"I_RAW{index}"
        add(f"J{index + 2}", f"ACS{index}_3WIRE", "sense",
            ["+3V3_SENS", "GND", raw], "header_h", "A", (78, y),
            ["VCC", "GND", "VOUT"])
    add("J6", "SW1_GND_ON", "logic", ["GND", "SW1_ON"], "header", "A", (94, 8))
    add("J7", "SW2_GND_ON", "logic", ["GND", "SW2_ON"], "header", "A", (94, 16))
    add("J8", "RELAY_GND_IN1_IN2_VCC_JDVCC", "logic",
        ["GND", "RELAY_IN1", "RELAY_IN2", "+5V_RELAY_VCC", "+5V_RELAY_COIL"], "header", "A", (94, 45))
    add("J9", "DPS_GND_TX_RX", "logic", ["GND", "DPS_TX", "DPS_RX"], "header", "A", (94, 25))
    add("J10", "OLED_GND_VDD_SCK_SDA", "logic", ["GND", "+3V3", "SCL", "SDA"], "header_h", "A", (43, 76))
    add("J11", "BUTTON", "logic", ["BTN", "GND"], "header_h", "A", (61, 76))
    add("J12", "SPI_3V3_GND_SCK_MISO_MOSI_CS", "logic",
        ["+3V3", "GND", "SCK", "MISO", "MOSI", "CS"], "header_h", "A", (43, 34))
    for ref, value, nets, position in [
            ("X1", "B1_B2_GND", ["B1", "B2", "GND"], (44, 5)),
            ("X2", "VIN_DC_GND", ["VIN_DC", "GND"], (61, 5)),
            ("X3", "5V_GND", ["+5V", "GND"], (8, 5)),
            ("X4", "DS18B20_3V3_DATA_GND", ["+3V3", "OW", "GND"], (78, 76)),
            ("X5", "U_LOAD_SENSE", ["LOAD+"], (94, 35))]:
        add(ref, value, "logic" if ref == "X4" else "power", nets, "terminal", "A", position)
    add("NT1", "COPPER_STAR_AT_X3", "power", ["+5V", "+5V_RELAY_VCC", "+5V_RELAY_COIL"], "net_tie", "A", (8, 5))
    add("VD1", "1N5819", "power", ["VIN_DC", "B1"], "D", "A", (43, 13), ["K", "A"])
    add("VD2", "1N5819", "power", ["VIN_DC", "B2"], "D", "A", (55, 13), ["K", "A"])
    for index, (source, destination, y) in enumerate([("B1", "U_B1", 42), ("B2", "U_B2", 49), ("LOAD+", "U_LOAD", 56)]):
        resistor(f"R{1 + 2 * index}", "100k_1%", source, destination, 45, y)
        resistor(f"R{2 + 2 * index}", "10k_1%" if index < 2 else "4.7k_1%", destination, "GND", 53, y)
        capacitor(f"C{3 + index}", "100n_50V", destination, "GND", 61, y)
    for index, (net, x, y) in enumerate([("I_B1", 45, 64), ("I_B2", 45, 71), ("I_LOAD", 70, 64)], 1):
        resistor(f"R{6 + index}", "1k", f"I_RAW{index}", net, x, y)
        capacitor(f"C{6 + index}", "1u_16V", net, "GND", x + 9, y)
    capacitor("C6", "100n_16V", "+3V3", "GND", 73, 34)
    resistor("R10", "4.7k", "SENS_PWR", "BASE3", 63, 22, "logic")
    resistor("R11", "10k", "BASE3", "+3V3", 72, 17, "logic")
    add("Q3", "BC557_CBE", "logic", ["+3V3_SENS", "BASE3", "+3V3"], "PNP", "A", (63, 15), ["C", "B", "E"])
    for index, y in [(1, 42), (2, 54)]:
        resistor(f"R{12 if index == 1 else 14}", "1k", f"K{index}", f"BASE{index}", 71, y, "logic")
        resistor(f"R{13 if index == 1 else 15}", "10k", f"BASE{index}", "GND", 71, y + 5, "logic")
        add(f"Q{index}", "BC547_CBE", "logic", [f"RELAY_IN{index}", f"BASE{index}", "GND"],
            "NPN", "A", (82, y), ["C", "B", "E"])
    resistor("R16", "4.7k", "SDA", "+3V3", 44, 20, "logic")
    resistor("R17", "4.7k", "SCL", "+3V3", 54, 20, "logic")
    resistor("R18", "4.7k", "OW", "+3V3", 68, 71, "logic")
    add("XLP", "LOAD_P06_P12_P13", "power", ["LOAD+"] * 3, "terminal")
    add("XGND", "GND_P24_P25_P26_P27_P28", "power", ["GND"] * 5, "terminal")
    capacitor("C1", "100u_50V_ALUMINIUM", "LOAD+", "GND", 0, 0, "power", "", "CP")
    capacitor("C2", "100n_50V", "LOAD+", "GND", 0, 0, "power", "", "C_bus")
    add("D3", "1.5KE33A_DNP", "power", ["LOAD+", "GND"], "TVS", names=["K", "A"])
    for index in [1, 2]:
        add(f"XB{index}", f"BAT{index}_PANEL", "power", [f"P{1 if index == 1 else 7:02}", "GND"], names=["+", "-"])
        add(f"F{index}", "ATO_15A", "power", [f"P{1 if index == 1 else 7:02}", f"P{2 if index == 1 else 8:02}"], "fuse")
        add(f"mACS{index}", "ACS711EX_15.5A", "power",
            [f"P{2 if index == 1 else 8:02}", f"B{index}", "+3V3_SENS", "GND", f"I_RAW{index}"],
            names=["IP-", "IP+", "VCC", "GND", "VOUT"],
            types=["passive", "passive", "power_in", "power_in", "output"])
        add(f"mSW{index}", "Pololu_2815_HP", "power", [f"B{index}", f"P{5 if index == 1 else 11:02}", "GND", f"SW{index}_ON"],
            names=["VIN", "VOUT", "GND", "ON"], types=["passive", "passive", "power_in", "input"])
        add(f"mDIO{index}", "XL74610", "power", ["LOAD+", f"P{5 if index == 1 else 11:02}"], "diode_module", names=["K", "A"])
    add("mACS3", "ACS711EX_15.5A", "power", ["LOAD+", "P14", "+3V3_SENS", "GND", "I_RAW3"],
        names=["IP-", "IP+", "VCC", "GND", "VOUT"],
        types=["passive", "passive", "power_in", "power_in", "output"])
    add("Fout", "ATO_15A", "power", ["P14", "LOAD_OUT+"], "fuse")
    add("XLOAD", "LOAD_PANEL", "power", ["LOAD_OUT+", "GND"], names=["+", "-"])
    add("XPSU", "PSU_33V_10A_PANEL", "charge", ["P22", "GND"], names=["+", "-"])
    add("mDPS", "DPS5015_9600_8N1_ADDR1", "charge", ["P22", "GND", "P16", "GND", None, "DPS_TX", "DPS_RX", "GND"],
        names=["IN+", "IN-", "OUT+", "OUT-", "V_UNUSED", "R_RXI", "T_TXO", "G_UART"],
        types=["power_in", "power_in", "power_out", "power_in", "passive", "input", "output", "power_in"])
    add("Fchg", "ATO_15A", "charge", ["P16", "P17"], "fuse")
    add("mDIO3", "XL74610", "charge", ["CHG", "P17"], "diode_module", names=["K", "A"])
    add("mREL2", "FL_3FF_5V_10A_REMOVE_JUMPER", "charge",
        ["CHG", "B1", None, "CHG", "B2", None, "GND", "RELAY_IN1", "RELAY_IN2", "+5V_RELAY_VCC", "+5V_RELAY_COIL"],
        names=["COM1", "NO1", "NC1", "COM2", "NO2", "NC2", "GND", "IN1", "IN2", "VCC", "JD_VCC"])
    add("mDC5", "LM2596_SET_5.0V_FIRST", "charge", ["VIN_DC", "GND", "+5V", "GND"],
        names=["IN+", "IN-", "OUT+", "OUT-"], types=["power_in", "power_in", "power_out", "power_in"])
    add("mOLED", "SSD1306_0x3C", "logic", ["GND", "+3V3", "SCL", "SDA"],
        names=["GND", "VDD", "SCK", "SDA"], types=["power_in", "power_in", "input", "bidirectional"])
    for index in [1, 2]:
        add(f"T{index}", "DS18B20_PROBE", "logic", ["+3V3", "OW", "GND"],
            names=["VCC", "DATA", "GND"], types=["power_in", "bidirectional", "power_in"])
    add("SW1", "PANEL_BUTTON_NO", "logic", ["BTN", "GND"], "switch")
    for net in ["GND", "VIN_DC", "+3V3_SENS", "P22"]:
        add("#FLG" + str(len(parts)), "PWR_FLAG", "charge", [net], "flag", types=["power_out"])
    for part in parts:
        if not part.ref[-1].isdigit():
            part.alias = part.ref
            part.ref += "1"
    pinout_path = Path(__file__).with_name("connector_pinout.json")
    if pinout_path.exists():
        pinouts = json.loads(pinout_path.read_text(encoding="utf-8"))
        by_ref = {part.ref: part for part in parts}
        allowed = {f"J{number}" for number in range(3, 13)} | {f"X{number}" for number in range(1, 6)}
        assert pinouts.keys() <= allowed
        for ref, nets in pinouts.items():
            part = by_ref[ref]
            pins_by_net = {pin[2]: pin for pin in part.pins}
            assert len(nets) == len(part.pins) and set(nets) == pins_by_net.keys(), ref
            part.pins = [(str(index + 1), pins_by_net[net][1], net, pins_by_net[net][3])
                         for index, net in enumerate(nets)]
            part.value = {"J8": "RELAY", "J9": "DPS_UART", "J10": "OLED_I2C", "J12": "SPI",
                          "X4": "DS18B20"}.get(ref, part.value)
    by_ref = {part.ref: part for part in parts}
    for ref in ["J3", "J4", "J5", "X5", "R1", "R2", "R3", "R4", "R5", "R6",
                "R7", "R8", "R9", "C3", "C4", "C5", "C7", "C8", "C9"]:
        by_ref[ref].board = "B"
        by_ref[ref].sheet = "sense"
    by_ref["J2"].board = ""
    by_ref["J2"].value = "ADS1115_0x48_EXTERNAL"
    by_ref["C6"].board = ""
    for ref in ["Q3", "R10", "R11"]:
        by_ref[ref].board = "C"
        by_ref[ref].sheet = "supply3"
    for ref in ["X1", "X2", "X3", "VD1", "VD2", "NT1", "J8"]:
        by_ref[ref].board = "D"
        by_ref[ref].sheet = "supply5"
    by_ref["J1"].pins = [(number, name, None if name in ["GPIO34", "GPIO39"] else net, pin_type)
                         for number, name, net, pin_type in by_ref["J1"].pins]
    add("J13", "ADS1115_0x49_EXTERNAL", "sense",
        ["+3V3", "GND", "SCL", "SDA", "+3V3", None, "I_LOAD", "U_LOAD", "GND", "GND"],
        "header_h", "", names=["VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"],
        types=["power_in", "power_in", "input", "bidirectional", "input", "open_collector", "input", "input", "input", "input"])
    capacitor("C10", "100n_16V", "+3V3", "GND", 0, 0, "sense", "")
    capacitor("C11", "100n_16V", "+3V3", "GND", 0, 0, "supply3", "C")
    capacitor("C12", "100n_16V", "+3V3_SENS", "GND", 0, 0, "supply3", "C")
    capacitor("C13", "100n_16V", "+5V", "GND", 0, 0, "supply5", "D")
    for ref, board, sheet, nets in [
            ("J20", "A", "logic", ["+3V3", "GND", "SCL", "SDA"]),
            ("J21", "A", "logic", ["+3V3", "GND", "SCL", "SDA"]),
            ("J22", "A", "logic", ["+3V3", "GND", "SENS_PWR"]),
            ("J23", "C", "supply3", ["+3V3", "GND", "SENS_PWR"]),
            ("J24", "C", "supply3", ["GND", "+3V3_SENS"]),
            ("J25", "B", "sense", ["GND", "+3V3_SENS"]),
            ("J26", "A", "logic", ["+5V", "GND"]),
            ("J27", "D", "supply5", ["+5V", "GND"]),
            ("J28", "A", "logic", ["RELAY_IN1", "RELAY_IN2", "GND"]),
            ("J29", "D", "supply5", ["RELAY_IN1", "RELAY_IN2", "GND"]),
            ("J30", "C", "supply3", ["+3V3", "GND"]),
            ("J31", "D", "supply5", ["+5V", "GND"]),
            ("J32", "B", "sense", ["I_B1", "I_B2", "U_B1", "U_B2", "GND"]),
            ("J33", "B", "sense", ["I_LOAD", "U_LOAD", "GND"])]:
        add(ref, "LINK_" + "_".join(nets), sheet, nets, "header_h", board, names=nets)
    add("X6", "BAT_SENSE_TO_B", "supply5", ["B1", "B2", "GND"], "terminal", "D", names=["B1", "B2", "GND"])
    add("X8", "BAT_SENSE_FROM_D", "sense", ["B1", "B2", "GND"], "terminal", "B", names=["B1", "B2", "GND"])
    return parts


def validate(parts):
    by_ref = {part.ref: part for part in parts}
    assert len(by_ref) == len(parts)
    pins = {name: net for _, name, net, _ in by_ref["J1"].pins}
    assert pins["GPIO39"] is None and pins["GPIO34"] is None
    assert pins["GPIO33"] == "SENS_PWR"
    assert pins["GPIO14"] is None
    assert ("8", "GPIO33", "SENS_PWR", "bidirectional") in by_ref["J1"].pins
    assert not any(net == "FAULT" for part in parts for _, _, net, _ in part.pins)
    assert all(pins[f"GPIO{number}"] is None for number in [0, 2, 6, 7, 8, 9, 10, 11, 12, 15])
    assert pins["GPIO22"] == "SCL" and pins["GPIO21"] == "SDA" and pins["GPIO23"] == "MOSI"
    assert [pin[2] for pin in by_ref["J2"].pins][-4:] == ["I_B1", "I_B2", "U_B1", "U_B2"]
    assert [pin[2] for pin in by_ref["J13"].pins][-4:] == ["I_LOAD", "U_LOAD", "GND", "GND"]
    assert by_ref["J2"].pins[4][2] == "GND" and by_ref["J13"].pins[4][2] == "+3V3"
    assert all(not by_ref[ref].board for ref in ["J2", "J13", "C6", "C10"])
    assert not any(net in ["SDA", "SCL", "+3V3"] for part in parts if part.board == "B"
                   for _, _, net, _ in part.pins)
    for ref in ["J20", "J21"]:
        assert by_ref[ref].board == "A"
        assert [pin[2] for pin in by_ref[ref].pins] == ["+3V3", "GND", "SCL", "SDA"]
    for ref, adc, channels in [("J32", "J2", 4), ("J33", "J13", 2)]:
        assert by_ref[ref].board == "B"
        assert [pin[2] for pin in by_ref[ref].pins] == [pin[2] for pin in by_ref[adc].pins[6:6+channels]] + ["GND"]
    assert {part.board for part in parts if part.board} == {"A", "B", "C", "D"}
    for first, second in [("J22", "J23"), ("J24", "J25"), ("J26", "J27"), ("J28", "J29"), ("X6", "X8")]:
        assert [pin[2] for pin in by_ref[first].pins] == [pin[2] for pin in by_ref[second].pins]
    for ref in ["mACS1", "mACS2", "mACS3"]:
        assert by_ref[ref].pins[0][1] == "IP-"
        assert [pin[1] for pin in by_ref[ref].pins[2:]] == ["VCC", "GND", "VOUT"]
    for ref in ["J3", "J4", "J5"]:
        assert len(by_ref[ref].pins) == 3
    assert 30 * 10 / 110 < 3.3
    assert 30 * 4.7 / 104.7 < 2.5
    print(f"Circuit checks passed: {len(parts)} parts")


if __name__ == "__main__":
    validate(circuit())