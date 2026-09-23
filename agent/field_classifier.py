def normalize(value):
    if value is None:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace("*", "")
    )


def classify_field(field):
    """
    Converts Workday / ATS controls into our internal field categories.

    Returns:

    {
        "mode": "PROFILE" | "MANUAL" | "IGNORE",
        "profile_path": "...",
        "category": "..."
    }
    """

    field_id = normalize(field.get("id"))
    name = normalize(field.get("name"))
    label = normalize(field.get("label"))
    tag = normalize(field.get("tag"))
    role = normalize(field.get("role"))
    aria_haspopup = normalize(
        field.get("aria_haspopup")
    )

    combined = " ".join(
        [
            field_id,
            name,
            label,
            tag,
            role,
            aria_haspopup,
        ]
    )

    # ==================================================
    # IGNORE WORKDAY UTILITY / NAVIGATION CONTROLS
    # ==================================================

    if field_id in {
        "languageselectorbutton",
        "settingsselectorbutton",
        "accountsettingsbutton",
    }:
        return {
            "mode": "IGNORE",
            "profile_path": None,
            "category": "workday_utility",
        }

    if (
        "legalnoticedeclinebutton" in combined
        or "backtojobposting" in combined
        or label == "decline"
        or "back to job posting" in label
    ):
        return {
            "mode": "IGNORE",
            "profile_path": None,
            "category": "navigation",
        }

    # ==================================================
    # FIRST NAME
    # ==================================================

    if (
        "firstname" in combined
        or "first name" in combined
        or "given name" in combined
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.first_name",
            "category": "first_name",
        }

    # ==================================================
    # LAST NAME
    # ==================================================

    if (
        "lastname" in combined
        or "last name" in combined
        or "surname" in combined
        or "family name" in combined
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.last_name",
            "category": "last_name",
        }

    # ==================================================
    # ADDRESS LINE 1
    # ==================================================

    if (
        "addressline1" in combined
        or "address line 1" in combined
        or "street address" in combined
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.address_line1",
            "category": "address_line1",
        }

    # ==================================================
    # ADDRESS LINE 2
    # ==================================================

    if (
        "addressline2" in combined
        or "address line 2" in combined
        or "apartment" in combined
        or "apt" in combined
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.address_line2",
            "category": "address_line2",
        }

    # ==================================================
    # CITY
    # ==================================================

    if (
        name == "city"
        or "address--city" in field_id
        or label == "city"
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.city",
            "category": "city",
        }

    # ==================================================
    # POSTAL CODE / ZIP
    # ==================================================

    if (
        "postalcode" in combined
        or "postal code" in combined
        or "zip code" in combined
        or "zipcode" in combined
        or label == "zip"
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.postal_code",
            "category": "postal_code",
        }

    # ==================================================
    # COUNTY
    # ==================================================

    if (
        name == "regionsubdivision1"
        or "address--regionsubdivision1" in field_id
        or label == "county"
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.county",
            "category": "county",
        }

    # ==================================================
    # COUNTRY PHONE CODE
    # Must come BEFORE generic phone checks.
    # ==================================================

    if (
        "countryphonecode" in combined
        or "country phone code" in label
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.country_phone_code",
            "category": "country_phone_code",
        }

    # ==================================================
    # COUNTRY
    # Workday:
    # id = country--country
    # ==================================================

    if (
        field_id == "country--country"
        or name == "country"
        or label.startswith("country ")
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.country",
            "category": "country",
        }

    # ==================================================
    # STATE
    # Workday:
    # id = address--countryRegion
    # name = countryRegion
    # ==================================================

    if (
        field_id == "address--countryregion"
        or name == "countryregion"
        or label == "state"
        or label.startswith("state ")
        or "state/province" in label
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.state",
            "category": "state",
        }

    # ==================================================
    # PHONE DEVICE TYPE
    # Workday:
    # id = phoneNumber--phoneType
    # ==================================================

    if (
        field_id == "phonenumber--phonetype"
        or name == "phonetype"
        or "phone device type" in label
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.phone_device_type",
            "category": "phone_device_type",
        }



    # ==================================================
    # PHONE EXTENSION
    # ==================================================

    if (
        name == "extension"
        or "phonenumber--extension" in field_id
        or "phone extension" in label
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.phone_extension",
            "category": "phone_extension",
        }

    # ==================================================
    # PHONE NUMBER
    # ==================================================

    if (
        name == "phonenumber"
        or field_id == "phonenumber--phonenumber"
        or label == "phone number"
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.phone_number",
            "category": "phone_number",
        }

    # ==================================================
    # JOB SOURCE
    # ==================================================

    if (
        "source--source" in field_id
        or "how did you hear about us" in label
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "application_defaults.job_source",
            "category": "job_source",
        }

    # ==================================================
    # PREVIOUS WORKER
    #
    # Keep MANUAL for this version.
    # We'll connect company history automatically next.
    # ==================================================

    if (
        name == "candidateispreviousworker"
        or "candidateispreviousworker" in combined
        or "previous worker" in combined
        or "previous employee" in combined
    ):
        return {
            "mode": "SPECIAL",
            "profile_path": None,
            "category": "previous_worker",
        }

    # ==================================================
    # EMAIL
    # ==================================================

    if (
        name == "email"
        or "email address" in label
        or label == "email"
    ):
        return {
            "mode": "PROFILE",
            "profile_path":
                "candidate.email",
            "category": "email",
        }

    # ==================================================
    # LINKEDIN
    # ==================================================

    if "linkedin" in combined:
        return {
            "mode": "PROFILE",
            "profile_path":
                "candidate.linkedin",
            "category": "linkedin",
        }

    # ==================================================
    # GITHUB
    # ==================================================

    if "github" in combined:
        return {
            "mode": "PROFILE",
            "profile_path":
                "candidate.github",
            "category": "github",
        }

    # ==================================================
    # UNKNOWN
    # ==================================================

    return {
        "mode": "IGNORE",
        "profile_path": None,
        "category": "unknown",
    }