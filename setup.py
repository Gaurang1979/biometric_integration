from setuptools import setup, find_packages

setup(
    name="biometric_integration",
    version="1.0.0",
    description="Direct Hikvision biometric integration for ERPNext",
    author="Sundaram Technologies",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
