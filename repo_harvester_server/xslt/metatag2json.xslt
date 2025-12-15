<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

    <xsl:output method="text" encoding="UTF-8"/>

    <xsl:template match="/">
<xsl:text>{
</xsl:text>
<xsl:text>  "title": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'title'"/></xsl:call-template><xsl:text>",
</xsl:text>
<xsl:text>  "resource_type": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'type'"/></xsl:call-template><xsl:text>",
</xsl:text>
<xsl:text>  "publisher": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'publisher'"/></xsl:call-template><xsl:text>",
</xsl:text>
<xsl:text>  "description": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'description'"/></xsl:call-template><xsl:text>",
</xsl:text>
<xsl:text>  "language": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'language'"/></xsl:call-template><xsl:text>",
</xsl:text>
<xsl:text>  "country": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'country'"/></xsl:call-template><xsl:text>",
</xsl:text>
<xsl:text>  "contact": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'contact'"/></xsl:call-template><xsl:text>",
</xsl:text>
<xsl:text>  "license": "</xsl:text><xsl:call-template name="get-meta"><xsl:with-param name="name" select="'license'"/></xsl:call-template><xsl:text>"
</xsl:text>
<xsl:text>}</xsl:text>
    </xsl:template>

    <!-- Template to get the first matching meta content -->
    <xsl:template name="get-meta">
        <xsl:param name="name"/> <!-- already lowercase -->
        <xsl:for-each select="//meta">
            <xsl:variable name="meta-lower" select="translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"/>
            <xsl:if test="$meta-lower = $name
                         or substring($meta-lower, string-length($meta-lower) - string-length($name), string-length($name) + 1) = concat('.', $name)">
                <xsl:value-of select="@content"/>
                <xsl:break/>
            </xsl:if>
        </xsl:for-each>
    </xsl:template>

</xsl:stylesheet>

