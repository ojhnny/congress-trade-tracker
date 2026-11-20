"""Command line entry point: ``congress-trades <step> [...]``.

Examples:

    congress-trades all                 # every step, then dbt build, then export
    congress-trades extract-house
    congress-trades load-raw dbt export
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from congress_trades import pipeline
from congress_trades.config import Settings

ORDER = [*pipeline.STEPS, "dbt", "export"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="congress-trades",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("steps", nargs="+", choices=[*ORDER, "all"])
    parser.add_argument("--run-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    steps = ORDER if "all" in args.steps else args.steps

    for step in steps:
        if step == "dbt":
            pipeline.run_dbt(settings, "build")
            result = "ok"
        elif step == "export":
            result = pipeline.export(settings)
        else:
            result = pipeline.STEPS[step](settings, args.run_date)
        print(f"{step}: {json.dumps(result, default=str)}")


if __name__ == "__main__":
    main()
