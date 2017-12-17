from setuptools import setup

setup(name="AmCAT",
      packages=["amcat"],
      package_data={"amcat": ["icons/*.svg"]},
      classifiers=["Example :: Invalid"],
      entry_points={"orange.widgets": "AmCAT = amcat"},
      )

