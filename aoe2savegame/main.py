import os
import time
import typing
import logging
from logging.config import dictConfig
from collections import defaultdict
from dataclasses import dataclass

import yaml
from plumbum import local, cli
from mgz import header, fast, enums
from rich.console import Console
from rich.table import Table
from diskcache import FanoutCache

logger = logging.getLogger("aoe2savegame.main")


class AOE2IDs:
    # https://halfon.aoe2.se/
    unit_id_to_name = {
        83: "Villager",
        93: "Spearman",
        448: "Scout Cavalry",
        13: "Fishing Ship",
        4: "Archer",
        74: "Militia",
    }

    building_id_to_name = {
        68: "Mill",
        562: "Lumber Camp",
        50: "Farm",
        12: "Barracks",
        584: "Mining Camp",
        103: "Blacksmith",
        101: "Stable",
        70: "House",
        84: "Market",
        804: "Palisade Gate",
        # This isn't a mistake, there's multiple archery ranges with different stats :/
        14: "Archery Range",
        87: "Archery Range",
        621: "Town Center",
        45: "Dock",
        67: "Fortified Gate",
    }

    technology_id_to_name = {
        101: "Feudal Age",
        22: "Loom",
        202: "Double Bit Axe",
        213: "Wheelbarrow",
        435: "Bloodlines",
        14: "Horse Collar",
        67: "Forging",
        55: "Gold Mining",
        222: "Man-at-Arms",
    }


class Util:
    @staticmethod
    def get_consecutive_count(values):
        """
        Given a list of values, return a list of tuples in form (value, count), where count is the number of identical values in a row.

        Example:
        Input: ["a", "a", "a", "c", "b", "b", "a"]
        Output: [("a", 3), ("c", 1), ("b", 2), ("a", 1)]
        """
        ret = []
        current = None
        count = 0
        for v in values:
            if current != v:
                if count > 0:
                    ret.append((current, count))
                current = v
                count = 1
            else:
                count += 1
        return ret

    @staticmethod
    def get_build_order(actions):
        bo = []

        for action, data in actions:
            if action == fast.Action.DE_QUEUE:
                unit_id = data["unit_id"]
                bo.append(AOE2IDs.unit_id_to_name.get(unit_id, unit_id))
            elif action == fast.Action.BUILD:
                building_id = data["building_id"]
                bo.append(AOE2IDs.building_id_to_name.get(building_id, building_id))
            elif action == fast.Action.RESEARCH:
                technology_id = data["technology_id"]
                bo.append(
                    AOE2IDs.technology_id_to_name.get(technology_id, technology_id)
                )
        return Util.get_consecutive_count(bo)


_cache = FanoutCache("/tmp/aoe2savegame")


@dataclass
class RawSaveGame:
    ops: typing.Any
    stream: typing.Any
    meta: typing.Any


@_cache.memoize()
def load_from_filename(filename):
    ops = []
    with local.path(filename).open("rb") as data:
        eof = os.fstat(data.fileno()).st_size
        logger.info("Reading header")
        stream = header.parse_stream(data)
        meta = fast.meta(data)
        logger.info("Finished reading header, reading ops")
        while data.tell() < eof:
            op = fast.operation(data)
            ops.append(op)
        logger.info("Finished reading ops")
    return RawSaveGame(ops, stream, meta)


class SaveGameAnalyser:
    def __init__(self, filename):
        logger.info("Initializing SaveGameAnalyzer")
        self.raw = load_from_filename(filename)
        logger.info("Finished loading")

        self.player_id_to_name = {
            p.player_number: p.name.value
            for p in self.raw.stream.de.players
            if p.player_number >= 0
        }

        self._generate_actions_by_player()

        self._generate_build_orders_by_player()

    def _generate_actions_by_player(self):
        logger.info("Generating actions by player")
        self.actions_by_player = defaultdict(list)
        for op in self.raw.ops:
            if op[0] == fast.Operation.ACTION:
                action, data = op[1]
                if action in [
                    fast.Action.DE_QUEUE,
                    fast.Action.BUILD,
                    fast.Action.RESEARCH,
                ]:
                    self.actions_by_player[data["player_id"]].append((action, data))

    def _generate_build_orders_by_player(self):
        logger.info("Generating build orders by player")
        self.build_orders_by_player = {
            player_id: Util.get_build_order(action)
            for player_id, action in self.actions_by_player.items()
        }

    def print_build_order_table(self, row_count=20):
        console = Console()

        table = Table(show_header=True, header_style="bold")

        for id, player in self.player_id_to_name.items():
            table.add_column(player.decode(), no_wrap=True, min_width=15)

        def format_bo_tuple(name, count):
            if count == 1:
                return f"{name}"
            return f"{name} x{count}"

        for i in range(row_count):
            table.add_row(
                *[
                    format_bo_tuple(*self.build_orders_by_player[p][i])
                    for p in self.player_id_to_name.keys()
                ]
            )

        console.print(table)


class SaveGameAnalysis(cli.Application):
    def main(self, filename):
        game = SaveGameAnalyser(filename)

        game.print_build_order_table(row_count=20)


if __name__ == "__main__":
    config = yaml.load(
        (local.path(__file__).parent.parent / "logging.yaml").read(),
        Loader=yaml.FullLoader,
    )
    dictConfig(config)

    SaveGameAnalysis.run()
