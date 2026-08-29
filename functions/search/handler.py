import re

# Construct a flexible regex pattern for search
cleaned_query = re.escape(user_query).replace(r"\ ", r".*")
search_pattern = {"file_name": {"$regex": cleaned_query, "$options": "i"}}
