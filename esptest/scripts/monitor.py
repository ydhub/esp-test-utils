import sys

try:
    from esp_idf_monitor.idf_monitor import main
except ImportError:
    print('can not import idf monitor, please install: "pip install esp-idf-monitor"')
    sys.exit(1)

if __name__ == '__main__':
    main()
