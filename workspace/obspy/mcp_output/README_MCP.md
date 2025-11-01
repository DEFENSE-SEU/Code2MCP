# ObsPy MCP (Model Context Protocol) Service

## Project Introduction

ObsPy is a Python framework designed for processing seismological data. It provides tools for reading and writing various seismic data formats, accessing remote data services, and performing advanced signal processing. The goal of ObsPy is to simplify and accelerate the development of seismological applications by offering a modular and extensible architecture.

Key features include:
- Support for multiple seismic data formats (e.g., MiniSEED, SAC, StationXML).
- Advanced signal processing utilities (e.g., filtering, resampling, cross-correlation).
- Tools for seismic travel time calculations and ray path modeling.
- Visualization capabilities for waveform plotting and focal mechanism beachballs.
- Client services for accessing remote seismic data centers.

## Installation Method

To install ObsPy, ensure you have Python 3.7 or later installed. Use the following command to install ObsPy and its dependencies:

pip install obspy

### Required Dependencies
- numpy
- scipy
- matplotlib
- lxml
- sqlalchemy
- future
- decorator
- requests
- setuptools

### Optional Dependencies
- cartopy
- pyproj
- h5py
- pandas
- pytest
- sphinx

For optional features, install the corresponding libraries as needed.

## Quick Start

Here is a quick guide to using ObsPy's core functionalities:

1. **Read seismic data**:
   Use the `read` function to load waveform data from supported formats.
   Example: `stream = obspy.read("example.mseed")`

2. **Process data**:
   Apply filters, merge traces, or resample data using the `Stream` object.
   Example: `stream.filter("bandpass", freqmin=1.0, freqmax=10.0)`

3. **Visualize data**:
   Plot waveforms or focal mechanisms.
   Example: `stream.plot()`

4. **Access remote data**:
   Use the FDSN client to fetch waveform or event data from data centers.
   Example: `client.get_waveforms(network="IU", station="ANMO", location="00", channel="BHZ", starttime=start, endtime=end)`

5. **Calculate travel times**:
   Use the TauPyModel service for seismic travel time calculations.
   Example: `model.get_travel_times(source_depth_in_km=10, distance_in_degree=30, phase_list=["P", "S"])`

## Available Tools and Endpoints List

### Core Services
- **Stream and Trace**: Handles seismic time series data, including reading, writing, merging, and splitting.
- **UTCDateTime**: Provides precise time handling for seismic data.
- **Event and Catalog**: Represents seismic events and collections of events.
- **Inventory**: Manages station metadata, including networks, stations, and channels.

### Signal Processing Services
- **Filtering**: Apply bandpass, lowpass, or highpass filters.
- **Resampling**: Change the sampling rate of seismic data.
- **Cross-correlation**: Perform cross-correlation analysis on seismic traces.

### I/O Services
- **MiniSEED**: Read and write MiniSEED files.
- **SAC**: Handle SAC format data.
- **StationXML**: Manage station metadata in StationXML format.

### Geodetic Calculations
- **Distance and Azimuth**: Calculate distances and azimuths between geographic coordinates.

### Visualization Services
- **Waveform Plotting**: Visualize seismic waveforms.
- **Beachball Plots**: Generate focal mechanism diagrams.

### Client Services
- **FDSN Web Services**: Access seismic data from remote data centers.
- **Mass Downloader**: Download large datasets from multiple data centers.

### TauPyModel Services
- **Travel Time Calculations**: Compute seismic travel times for predefined Earth models.
- **Ray Path Modeling**: Visualize ray paths for seismic phases.

### Command-Line Tools
- **obspy-runtests**: Run the ObsPy test suite.
- **obspy-flinnengdahl**: Generate Flinn-Engdahl region names for coordinates.
- **obspy-reftekrescue**: Rescue data from Reftek recorders.
- **obspy-sds-html-report**: Generate HTML reports for SDS waveform archives.

## Common Issues and Notes

1. **Dependencies**:
   Ensure all required dependencies are installed. Use `pip install obspy[all]` to include optional dependencies for full functionality.

2. **Environment**:
   ObsPy is compatible with Python 3.7 and later. It is recommended to use a virtual environment to manage dependencies.

3. **Performance**:
   For large datasets, consider optimizing memory usage by processing data in chunks or using efficient file formats like MiniSEED.

4. **Data Access**:
   When using client services, ensure you have a stable internet connection and valid credentials for restricted data centers.

5. **Visualization**:
   For advanced plotting (e.g., maps), install optional dependencies like `cartopy` and `pyproj`.

## Reference Links or Documentation

- [ObsPy GitHub Repository](https://github.com/obspy/obspy)
- [ObsPy Documentation](https://docs.obspy.org)
- [ObsPy Tutorials](https://docs.obspy.org/tutorial/)
- [ObsPy API Reference](https://docs.obspy.org/packages/autogen/obspy.core.html)

For further assistance, refer to the [CONTRIBUTING.md](https://github.com/obspy/obspy/blob/master/CONTRIBUTING.md) and [README.md](https://github.com/obspy/obspy/blob/master/README.md) files in the repository.