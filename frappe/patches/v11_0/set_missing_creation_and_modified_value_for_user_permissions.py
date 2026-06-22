# import frappe


# def execute():
# 	frappe.db.sql(
# 		"""UPDATE `tabUser Permission`
# 		SET `modified`=NOW(), `creation`=NOW()
# 		WHERE `creation` IS NULL"""
# 	)


import frappe


def execute():
        if frappe.db.db_type == "postgres":
                frappe.db.sql("""
                        UPDATE "tabUser Permission"
                        SET "modified" = NOW(),
                                "creation" = NOW()
                        WHERE "creation" IS NULL
                """)
        else:
                frappe.db.sql("""
                        UPDATE `tabUser Permission`
                        SET `modified` = NOW(),
                                `creation` = NOW()
                        WHERE `creation` IS NULL
                """)