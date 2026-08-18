# Dateutil MCP (Model Context Protocol) Service

## Project Introduction

The `dateutil` library is a powerful Python package that extends the functionality of Python's standard `datetime` module. It provides advanced date and time manipulation capabilities, including flexible parsing, timezone handling, relative date arithmetic, recurrence rule processing, and Easter date calculations. The library adheres to international standards such as ISO 8601 and iCalendar (RFC 5545) and maintains an up-to-date timezone database based on the IANA Olson database.

## Installation Method

To install the `dateutil` MCP service, ensure you have Python 3.3+ installed. Use the following command to install via pip:

```
pip install python-dateutil
```

### Dependencies:
- Required: `datetime`, `six`
- Optional: `tzdata` (for timezone database updates)

## Quick Start

Here are examples of how to use the main functions provided by the `dateutil` MCP service:

### Parsing Dates
Use the `parse` function to flexibly parse date/time strings:
```
from dateutil.parser import parse
date = parse("2023-10-01")
```

### Timezone Handling
Retrieve timezone information using `gettz`:
```
from dateutil.tz import gettz
timezone = gettz("America/New_York")
```

### Relative Date Arithmetic
Perform relative date calculations using `relativedelta`:
```
from dateutil.relativedelta import relativedelta
from datetime import datetime
new_date = datetime.now() + relativedelta(months=+1)
```

### Recurrence Rules
Generate recurrence rules using `rrule`:
```
from dateutil.rrule import rrule, DAILY
from datetime import datetime
rules = rrule(DAILY, count=5, dtstart=datetime(2023, 10, 1))
```

### Easter Date Calculation
Calculate Easter Sunday for a given year:
```
from dateutil.easter import easter
easter_date = easter(2023)
```

### Timezone Database Updates
Automate timezone database updates using the `updatezinfo` CLI tool:
```
python updatezinfo.py
```

## Available Tools and Endpoints List

### Core Modules:
1. **Parser (`dateutil.parser`)**  
   Functions: `parse`, `isoparse`  
   Description: Handles flexible date/time string parsing, including ISO 8601 compliance.

2. **Timezone Handling (`dateutil.tz`)**  
   Functions: `gettz`, `tzfile`, `tzlocal`, `tzutc`  
   Classes: `tzrange`, `tzoffset`  
   Description: Provides timezone handling, including local timezone detection and UTC support.

3. **Relative Delta (`dateutil.relativedelta`)**  
   Functions: `relativedelta`  
   Classes: `relativedelta`  
   Description: Implements relative date arithmetic for operations like adding months or years.

4. **Recurrence Rules (`dateutil.rrule`)**  
   Functions: `rrule`, `rruleset`, `rrulestr`  
   Classes: `rrule`, `rruleset`  
   Description: Handles recurrence rules based on iCalendar RFC 5545 specifications.

5. **Easter Calculation (`dateutil.easter`)**  
   Functions: `easter`  
   Description: Calculates the date of Easter Sunday for a given year.

6. **Timezone Database Management (`dateutil.zoneinfo`)**  
   Functions: `get_zonefile_instance`, `rebuild`  
   Classes: `ZoneInfoFile`  
   Description: Manages timezone database updates and metadata verification.

### CLI Tool:
- **Update Timezone Database (`updatezinfo`)**  
  Description: Automates updates to the timezone database using the IANA Olson database.

## Common Issues and Notes

1. **Dependencies**: Ensure required dependencies (`datetime`, `six`) are installed. For timezone database updates, consider installing `tzdata`.
2. **Environment**: The library supports Python 3.3+ and is compatible with Unix and Windows platforms.
3. **Performance**: Parsing large datasets or complex recurrence rules may require optimization.
4. **Timezone Updates**: Use the `updatezinfo` tool to keep the timezone database current.
5. **Backward Compatibility**: The library supports Python 2.7 but is primarily optimized for Python 3.

## Reference Links or Documentation

- [GitHub Repository](https://github.com/dateutil/dateutil)
- [Official Documentation](https://dateutil.readthedocs.io/en/stable/)
- [Python Package Index (PyPI)](https://pypi.org/project/python-dateutil/)
- [Contribution Guidelines](https://github.com/dateutil/dateutil/blob/master/CONTRIBUTING.md)

For further details, refer to the official documentation and examples provided in the repository.