# Yade MCP Plugin

## Project Overview

Yade is a powerful open-source project focused on the simulation and analysis of the Discrete Element Method (DEM). It provides a rich set of functional modules, including geometry processing, particle packing, a graphical user interface (GUI), runtime management, and testing tools. Yade's modular design makes it suitable for scientific research, engineering simulations, and educational purposes.

This project extends Yade's functionality with an MCP (Model Context Protocol) plugin, allowing its core features to be encapsulated as independent services for easy integration into distributed systems or microservices architectures.

## Features

- **Modular Design**: Supports various functional modules, including geometry processing, particle packing, runtime management, etc.
- **Graphical User Interface**: GUI based on Qt4 and Qt5, supporting OpenGL rendering and interaction.
- **Testing Tools**: Built-in testing module for verifying the correctness of core functions and engines.
- **Highly Extensible**: Supports extensions in Python and C++, making it easy for developers to customize functionality.
- **MCP Support**: Provides standardized service interfaces through the MCP plugin for easy integration and extension.

## Installation

### System Requirements

- **Operating System**: Linux (Ubuntu recommended), Windows, macOS
- **Python Version**: >= 3.6
- **Dependencies**:
  - Required: NumPy, PyQt4/PyQt5, OpenGL, CGAL, Eigen3
  - Optional: Matplotlib, PyGTS, Cholmod

### Installation Steps

1.  **Clone the repository**

    ```
    git clone https://github.com/gohsianghuat/Yade.git
    cd Yade
    ```

2.  **Install dependencies**
    -   Use the system package manager to install dependencies:

        ```
        sudo apt-get install -y build-essential cmake libqt4-dev libqt5-dev python3-dev python3-numpy libeigen3-dev libcgal-dev
        ```

    -   Optional dependencies:

        ```
        sudo apt-get install -y python3-matplotlib python3-pygts python3-cholmod
        ```

3.  **Build the project**

    ```
    mkdir build
    cd build
    cmake ..
    make -j$(nproc)
    ```

4.  **Install the MCP plugin**

    ```
    pip install -r mcp_output/requirements.txt
    ```

5.  **Verify the installation**

    ```
    ./bin/yade --test
    ```

## Usage

### Run the default test scene

Run the default test to verify functionality:

```
./bin/yade -j$(nproc) --test
```

### Start the graphical user interface

Start Yade with the Qt5 GUI:

```
./bin/yade-qt5
```

### Use the MCP service

Run the service through the MCP plugin:

```
python mcp_output/start_mcp.py
```

### Example scripts

Yade provides a rich set of example scripts located in the `examples/` directory. For example:

-   **Gravity deposition**: `examples/02-gravity-deposition.py`
-   **Periodic simple shear**: `examples/04-periodic-simple-shear.py`
-   **Triaxial test**: `examples/06-periodic-triaxial-test.py`

Run an example script:

```
./bin/yade examples/02-gravity-deposition.py
```

## Available Tool Endpoints

The following are the tool endpoints provided by the MCP plugin:

### CLI Commands

-   `yade`

    Used to run predefined simulation scenarios.
    Example:

    ```
    yade examples/02-gravity-deposition.py
    ```

-   `yade --test`

    Runs the default test scene to verify functionality.
    Example:

    ```
    yade --test
    ```

-   `install-requires.sh`

    A script to install the project environment on an Ubuntu system.
    Example:

    ```
    ./install-requires.sh
    ```

### Core Modules

-   `gui.qt4`

    Provides graphical user interface functionality based on Qt4, including OpenGL rendering and interaction.

-   `gui.qt5`

    Provides graphical user interface functionality based on Qt5, similar to the Qt4 module but with support for a more modern version of Qt.

-   `tests`

    Contains the testing module for verifying core functions and engines.

-   `pack`

    Provides particle packing and geometry processing functionality, supporting various packing algorithms.

-   `py_geometry`

    Geometry processing module, supporting polyhedron and mesh-related operations.

-   `runtime`

    Runtime management module, providing system configuration and time management functions.

## Notes

1.  **Dependency installation issues**
    -   Some dependencies may need to be installed manually, especially on non-Ubuntu systems.
    -   If you encounter missing dependency issues, please refer to the official documentation or contact the maintainers.

2.  **Compatibility issues**
    -   The Qt4 and Qt5 modules may have compatibility issues. Please choose the appropriate version based on your system environment.

3.  **Performance optimization**
    -   For large-scale simulation scenarios, it is recommended to use multi-threading or distributed computing features.

4.  **Example script paths**
    -   Ensure that the script paths are correct when running scripts to avoid file-not-found errors.

## Troubleshooting

### Common Issues

-   **Problem: Dependency installation fails**
    Solution: Check if the system package manager is working correctly, or try to install the dependencies manually.

-   **Problem: GUI fails to start**
    Solution: Ensure that PyQt4 or PyQt5 is installed, and select the appropriate version based on your system environment.

-   **Problem: Script runs with an error**
    Solution: Check if the script path is correct, or view the logs for detailed error information.

-   **Problem: MCP service fails to start**
    Solution: Check if the MCP plugin is installed correctly and ensure that the port is not already in use.

### Getting Help

If you encounter other issues, please get help through the following channels:

-   Submit an Issue: [GitHub Issues](https://github.com/gohsianghuat/Yade/issues)
-   Contact the maintainer: `gohsianghuat@gmail.com`

## Contribution Guidelines

Contributions of code and improvement suggestions are welcome! Please follow these steps:

1.  Fork the repository.
2.  Create a new branch: `git checkout -b feature/your-feature-name`
3.  Commit your changes: `git commit -m "Add your feature"`
4.  Push the branch: `git push origin feature/your-feature-name`
5.  Submit a Pull Request.

## License

This project is open-sourced under the [GPLv3](LICENSE) license. You are free to use, modify, and distribute it, but you must comply with the terms of the license.

---

Thank you for using the Yade MCP plugin! If you have any questions or suggestions, please feel free to contact us.